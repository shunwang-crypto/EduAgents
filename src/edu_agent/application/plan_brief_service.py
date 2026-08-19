"""PlanBriefService：为用户解释“为什么这样安排学习计划”。

从已存在的结构化结果（StudyPlan / KCGraph / LearnerModel / PlanContext）确定性构建，
不额外随意调用 LLM。目标：第一页一眼看懂目标、关键路径、为什么这样安排、难点、调整规则。
"""

from __future__ import annotations

import logging
import json
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from edu_agent.application.course_graph_service import CourseGraphService
from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger("edu_agent.application.plan_brief")


class StageOverview(BaseModel):
    stage_id: str
    title: str
    objective: str
    order: int
    kc_count: int


class PathItem(BaseModel):
    kc_id: str
    name: str


class PlanBrief(BaseModel):
    course_id: str
    plan_id: str
    goal: str
    target_outcome: str = ""

    why_this_plan: List[str] = Field(default_factory=list)
    stage_overview: List[StageOverview] = Field(default_factory=list)
    critical_path: List[PathItem] = Field(default_factory=list)
    difficulty_hotspots: List[str] = Field(default_factory=list)
    known_skills: List[str] = Field(default_factory=list)
    skill_gaps: List[str] = Field(default_factory=list)
    unassessed_skills: List[str] = Field(default_factory=list)
    adaptation_rules: List[str] = Field(default_factory=list)
    time_budget: str = ""


class PlanBriefService:
    def __init__(self, learner: LearnerModelService) -> None:
        self.learner = learner
        self.graph_service = CourseGraphService(learner._repo)

    def build(
        self,
        user_id: str,
        course_id: str,
        plan_context: Optional[dict] = None,
        force_hotspots: Optional[List[str]] = None,
    ) -> PlanBrief:
        plan = self.learner.repo.get_plan(user_id, course_id)
        if plan is None:
            raise KeyError("no plan for course")
        steps = self.learner.repo.list_plan_steps(plan["plan_id"])

        active = self.graph_service.load_active_graph(user_id, course_id)
        course = active.course if active else Course(course_id=course_id, title=plan.get("title", ""))

        # goal / target_outcome
        goal = plan.get("title", "")
        bundle = self.learner.build_bundle(user_id, course_id)
        if bundle.active_goal is not None:
            goal = (bundle.active_goal.target or bundle.active_goal.goal_name or "").strip() or goal

        # UNKNOWN != skill gap（§10）：mastery missing ≠ mastery 0。
        # 拆成三类：known / skill_gaps / unassessed。
        mastery_map: Dict[str, Optional[float]] = {}
        for item in bundle.course_state.knowledge:
            mastery_map[item.kc_id] = item.mastery
        known_skills = [
            c.title for c in course.components
            if mastery_map.get(c.kc_id) is not None and mastery_map.get(c.kc_id) >= 0.7
        ][:8]
        skill_gaps = [
            c.title for c in course.components
            if mastery_map.get(c.kc_id) is not None and mastery_map.get(c.kc_id) < 0.7
        ][:8]
        unassessed_skills = [
            c.title for c in course.components
            if mastery_map.get(c.kc_id) is None
        ][:8]

        # critical path：真实 DAG longest path（§42）
        critical_path = self._critical_path(course)

        # stage overview（结构化 StudyPlan 是唯一真值）
        stage_overview: List[StageOverview] = []
        by_stage: Dict[int, List[dict]] = {}
        for s in steps:
            order = int(s.get("stage_order") or 1)
            by_stage.setdefault(order, []).append(s)
        for order in sorted(by_stage):
            group = by_stage[order]
            stage_overview.append(
                StageOverview(
                    stage_id=group[0].get("stage_id") or f"stage-{order}",
                    title=group[0].get("stage_title") or f"阶段 {order}",
                    objective="",
                    order=order,
                    kc_count=len(group),
                )
            )

        # why_this_plan / adaptation_rules（确定性，来自 learner 状态；§9 不出现内部术语）
        why = [
            f"目标：{goal}",
        ]
        if known_skills:
            why.append("你已经具备：" + "、".join(known_skills[:4]))
        if skill_gaps:
            why.append("建议加强：" + "、".join(skill_gaps[:4]))

        adaptation_rules = [
            "如果后续学习结果表明某个知识点已经掌握，系统会减少重复基础内容。",
            "如果后续实践表明某个前置知识仍需加强，系统会调整推荐路径。",
        ]

        pc = plan_context or {}
        time_budget = (
            f"{pc.get('duration_days')} 天 · 每天 {pc.get('daily_minutes')} 分钟"
            if pc.get("duration_days") else ""
        )

        return PlanBrief(
            course_id=course_id,
            plan_id=plan["plan_id"],
            goal=goal,
            target_outcome=goal,
            why_this_plan=why,
            stage_overview=stage_overview,
            critical_path=critical_path,
            difficulty_hotspots=force_hotspots if force_hotspots else self._difficulty_hotspots(steps),
            known_skills=known_skills,
            skill_gaps=skill_gaps,
            unassessed_skills=unassessed_skills,
            adaptation_rules=adaptation_rules,
            time_budget=time_budget,
        )

    def get(self, user_id: str, course_id: str) -> dict:
        return self.build(user_id, course_id).model_dump(mode="json")

    @staticmethod
    def _critical_path(course: Course) -> List[PathItem]:
        """真实 DAG 最长路径（§42）：DP on topological order。

        dist[node] = 1 + max(dist[prereq]); parent 回溯。
        保证返回路径中相邻节点之间都有 prerequisite edge。
        """
        if not course.components:
            return []
        nodes = [c.kc_id for c in course.components]
        # 建图：from_kc -> [to_kc]
        children: Dict[str, List[str]] = {k: [] for k in nodes}
        indeg: Dict[str, int] = {k: 0 for k in nodes}
        for r in course.relations:
            if r.relation == "prerequisite" and r.from_kc in children and r.to_kc in indeg:
                children[r.from_kc].append(r.to_kc)
                indeg[r.to_kc] += 1
        # Kahn 拓扑序
        order: List[str] = []
        queue = [k for k, d in indeg.items() if d == 0]
        while queue:
            k = queue.pop(0)
            order.append(k)
            for c in children.get(k, []):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        # 若存在环（不应有），用原始顺序兜底
        if len(order) != len(nodes):
            order = nodes

        dist: Dict[str, int] = {}
        parent: Dict[str, Optional[str]] = {}
        for k in order:
            best = 0
            best_p: Optional[str] = None
            for p in course.prerequisites(k):
                if dist.get(p, 0) + 1 > best:
                    best = dist.get(p, 0) + 1
                    best_p = p
            dist[k] = best
            parent[k] = best_p
        # 找到 dist 最大的节点（末端最长链终点）
        end = max(nodes, key=lambda k: dist.get(k, 0))
        path_ids: List[str] = []
        cur: Optional[str] = end
        while cur is not None:
            path_ids.append(cur)
            cur = parent.get(cur)
        path_ids.reverse()
        # 相邻节点有 edge 保证（DP 只从 prerequisite 回溯）
        title_of = {c.kc_id: c.title for c in course.components}
        return [PathItem(kc_id=k, name=title_of.get(k, k)) for k in path_ids[:8]]

    @staticmethod
    def _difficulty_hotspots(steps: List[dict]) -> List[str]:
        """§30：退化为按 difficulty 标记的硬/进阶步骤。

        结构化 difficulty_points 由 plan generation 时持久化到 PlanBrief
        （build 传入 difficulty_hotspots override），见 build(force_hotspots=...)。
        """
        hard = [
            s.get("title", "") for s in steps
            if (s.get("difficulty") or "").lower() in ("hard", "difficult", "困难", "advanced", "进阶")
        ]
        return hard[:5]
