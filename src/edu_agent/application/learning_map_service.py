"""Learning Map 应用层服务。

职责：Course（KC DAG）+ LearnerModelService + Adaptive Policy → LearningMap DTO。

不直接写业务逻辑到 api/router.py。所有 mastery 来自 LearnerModelService（唯一 Source of Truth）。
UNKNOWN 必须表示为 mastery=None，绝不为 0。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy
from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_graph_service import CourseGraphService

logger = logging.getLogger("edu_agent.application.learning_map")


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


class LearningMapNode(BaseModel):
    id: str
    name: str
    description: str = ""
    difficulty: str = "medium"

    mastery: Optional[float] = None          # None = 未评估（UNKNOWN）
    confidence: Optional[float] = None
    status: str = "unknown"                  # unknown/weak/learning/mastered

    recommended: bool = False
    locked: bool = False

    prerequisites: List[str] = Field(default_factory=list)
    misconceptions: List[str] = Field(default_factory=list)
    recent_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class LearningMapEdge(BaseModel):
    source: str
    target: str
    relation: str = "prerequisite"
    weight: float = 1.0


class LearningMapResponse(BaseModel):
    course_id: str
    goal: str
    nodes: List[LearningMapNode] = Field(default_factory=list)
    edges: List[LearningMapEdge] = Field(default_factory=list)
    recommended_path: List[str] = Field(default_factory=list)
    current_recommended_kc: Optional[str] = None
    graph_source: Optional[str] = None        # generated / builtin / legacy
    graph_version: Optional[int] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LearningMapService:
    """构建 LearningMapResponse。

    图来源遵循统一优先级：动态 persisted KCGraph > 内置 course > 无图。
    """

    def __init__(self, learner_model: LearnerModelService) -> None:
        self.learner_model = learner_model
        self.graph_service = CourseGraphService(self.learner_model._repo)

    def build(self, user_id: str, course_id: str) -> LearningMapResponse:
        active = self.graph_service.load_active_graph(user_id, course_id)
        # Legacy：旧课程有 StudyPlan 但无 graph → 尝试从 plan_steps 恢复（自动 migrate）。
        if active is None:
            plan = self.learner_model.repo.get_plan(user_id, course_id)
            if plan is not None:
                course_row = self.learner_model.repo.get_user_course(user_id, course_id)
                display = (course_row or {}).get("display_name") or course_id
                active = self.graph_service.try_recover_from_plan(
                    user_id, course_id, display_name=display
                )
        if active is None:
            # 无 plan 也无 graph → 明确「需生成计划/需升级」，不是「无计划」误导。
            raise ValueError(f"course not found: {course_id}")
        course = active.course
        graph_source = active.graph_source
        graph_version = active.graph_version

        bundle = self.learner_model.build_bundle(user_id, course_id)
        knowledge = bundle.course_state.knowledge
        km = {item.kc_id: item for item in knowledge}

        # P2-3：动态 graph 快照可能不含 goal（旧库）。可靠地从当前 active goal
        # 派生，避免 LearningMap.goal == ""（不重复存储，从唯一 Source of Truth 读取）。
        goal = course.goal
        if not goal or not goal.strip():
            active_goal = bundle.active_goal
            if active_goal is not None:
                goal = (active_goal.target or active_goal.goal_name or "").strip()
        if not goal:
            goal = course.goal

        # mastery / confidence / misconceptions 派生
        mastery_map: Dict[str, Optional[float]] = {}
        conf_map: Dict[str, Optional[float]] = {}
        misconception_map: Dict[str, List[str]] = {}
        recent_evidence_map: Dict[str, List[Dict[str, Any]]] = {}

        for c in course.components:
            item = km.get(c.kc_id)
            mastery_map[c.kc_id] = item.mastery if item else None
            conf_map[c.kc_id] = item.confidence if item else None

        events = self.learner_model.get_events(user_id, course_id, limit=200)
        for ev in events:
            kc = ev.get("kc_id") or (ev.get("payload") or {}).get("kc_id")
            if not kc:
                continue
            payload = ev.get("payload") or {}
            if payload.get("event_type_inner") == "tutor_turn" or payload.get("evidence_type") == "tutor_turn":
                rec = {
                    "kc_id": kc,
                    "type": payload.get("evidence_type", "tutor_turn"),
                    "correctness": payload.get("correctness"),
                    "difficulty": payload.get("difficulty"),
                    "hint_level": payload.get("hint_level"),
                    "confidence": payload.get("confidence"),
                    "misconceptions": payload.get("misconceptions", []),
                    "timestamp": ev.get("timestamp"),
                }
                recent_evidence_map.setdefault(kc, []).append(rec)
                for m in payload.get("misconceptions", []):
                    misconception_map.setdefault(kc, [])
                    if m not in misconception_map[kc]:
                        misconception_map[kc].append(m)

        # P2-1：recent_error 只看最近 N 条 tutoring evidence；最新一条为 incorrect 才标。
        _recent_error_map = {
            k: bool(v and v[0].get("correctness") == "incorrect")
            for k, v in recent_evidence_map.items()
        }

        goal_kcs = [c.kc_id for c in course.components]
        policy = HeuristicAdaptivePolicy(course, goal_kcs=goal_kcs)
        recommended_path = policy.recommended_path(
            mastery_map, misconception_map, _recent_error_map,
        )

        nodes: List[LearningMapNode] = []
        for c in course.components:
            eval_res = policy.evaluate_kc(
                c.kc_id, mastery_map, misconception_map, _recent_error_map,
            )
            nodes.append(
                LearningMapNode(
                    id=c.kc_id,
                    name=c.title,
                    description=c.description,
                    difficulty=c.difficulty,
                    mastery=mastery_map.get(c.kc_id),
                    confidence=conf_map.get(c.kc_id),
                    status=eval_res["status"],
                    recommended=eval_res["recommended"],
                    locked=eval_res["locked"],
                    prerequisites=course.prerequisites(c.kc_id),
                    misconceptions=misconception_map.get(c.kc_id, []),
                    recent_evidence=recent_evidence_map.get(c.kc_id, []),
                    reason_codes=eval_res["reason_codes"],
                )
            )

        edges: List[LearningMapEdge] = []
        for r in course.relations:
            if r.relation == "prerequisite":
                edges.append(LearningMapEdge(source=r.from_kc, target=r.to_kc,
                                             relation=r.relation, weight=r.weight))

        return LearningMapResponse(
            course_id=course.course_id,
            goal=goal,
            nodes=nodes,
            edges=edges,
            recommended_path=recommended_path,
            current_recommended_kc=recommended_path[0] if recommended_path else None,
            graph_source=graph_source,
            graph_version=graph_version,
        )
