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
        if active is None:
            raise ValueError(f"course not found: {course_id}")
        course = active.course
        graph_source = active.graph_source
        graph_version = active.graph_version

        bundle = self.learner_model.build_bundle(user_id, course_id)
        knowledge = bundle.course_state.knowledge
        km = {item.kc_id: item for item in knowledge}

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

        goal_kcs = [c.kc_id for c in course.components]
        policy = HeuristicAdaptivePolicy(course, goal_kcs=goal_kcs)
        recommended_path = policy.recommended_path(
            mastery_map, misconception_map,
            {k: True for k, v in recent_evidence_map.items()
             if any(e.get("correctness") == "incorrect" for e in recent_evidence_map[k])},
        )

        nodes: List[LearningMapNode] = []
        for c in course.components:
            eval_res = policy.evaluate_kc(
                c.kc_id, mastery_map, misconception_map,
                {k: True for k, v in recent_evidence_map.items()
                 if any(e.get("correctness") == "incorrect" for e in recent_evidence_map[k])},
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
            goal=course.goal,
            nodes=nodes,
            edges=edges,
            recommended_path=recommended_path,
            current_recommended_kc=recommended_path[0] if recommended_path else None,
            graph_source=graph_source,
            graph_version=graph_version,
        )
