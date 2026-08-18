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


class PlanBrief(BaseModel):
    course_id: str
    plan_id: str
    goal: str
    target_outcome: str = ""

    why_this_plan: List[str] = Field(default_factory=list)
    stage_overview: List[StageOverview] = Field(default_factory=list)
    critical_path: List[str] = Field(default_factory=list)   # kc_id 列表
    difficulty_hotspots: List[str] = Field(default_factory=list)
    known_skills: List[str] = Field(default_factory=list)
    skill_gaps: List[str] = Field(default_factory=list)
    adaptation_rules: List[str] = Field(default_factory=list)
    time_budget: str = ""


class PlanBriefService:
    def __init__(self, learner: LearnerModelService) -> None:
        self.learner = learner
        self.graph_service = CourseGraphService(learner._repo)

    def build(self, user_id: str, course_id: str, plan_context: Optional[dict] = None) -> PlanBrief:
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

        # known skills / skill gaps（来自 learner mastery；mastery>=0.7 → known）
        mastery_map: Dict[str, float] = {}
        for item in bundle.course_state.knowledge:
            if item.mastery is not None:
                mastery_map[item.kc_id] = item.mastery
        known_skills = [
            c.title for c in course.components
            if mastery_map.get(c.kc_id, 0) >= 0.7
        ][:8]
        skill_gaps = [
            c.title for c in course.components
            if mastery_map.get(c.kc_id, 0) < 0.7
        ][:8]

        # critical path：从 recommended_path 或 KCGraph 的“目标后继”推导
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

        # why_this_plan / adaptation_rules（确定性，来自 learner 状态）
        why = [
            f"目标：{goal}",
        ]
        if known_skills:
            why.append("你已经具备：" + "、".join(known_skills[:4]))
        if skill_gaps:
            why.append("当前主要能力缺口：" + "、".join(skill_gaps[:4]))

        adaptation_rules = [
            "如果 Learner Model 显示某知识点已掌握，系统会跳过重复基础内容。",
            "如果外部实践结果显示某前置知识仍薄弱，系统会重新调整推荐路径。",
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
            difficulty_hotspots=self._difficulty_hotspots(steps),
            known_skills=known_skills,
            skill_gaps=skill_gaps,
            adaptation_rules=adaptation_rules,
            time_budget=time_budget,
        )

    def get(self, user_id: str, course_id: str) -> dict:
        return self.build(user_id, course_id).model_dump(mode="json")

    @staticmethod
    def _critical_path(course: Course) -> List[str]:
        """从 KCGraph 推导一条关键路径（无环；取最长依赖链）。"""
        if not course.components:
            return []
        # 拓扑排序后的依赖链
        order: List[str] = []
        indeg = {c.kc_id: 0 for c in course.components}
        children: Dict[str, List[str]] = {c.kc_id: [] for c in course.components}
        for r in course.relations:
            if r.relation == "prerequisite":
                indeg[r.to_kc] = indeg.get(r.to_kc, 0) + 1
                children.setdefault(r.from_kc, []).append(r.to_kc)
        queue = [k for k, d in indeg.items() if d == 0]
        while queue:
            k = queue.pop(0)
            order.append(k)
            for c in children.get(k, []):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        # 从最后一个入序节点向前回溯最长链（简化：直接取 topological 顺序的尾部子序列）
        if not order:
            return [c.kc_id for c in course.components]
        return order[-min(len(order), 5):]

    @staticmethod
    def _difficulty_hotspots(steps: List[dict]) -> List[str]:
        hard = [s.get("title", "") for s in steps if (s.get("difficulty") or "").lower() in ("hard", "difficult", "困难")]
        return hard[:5]
