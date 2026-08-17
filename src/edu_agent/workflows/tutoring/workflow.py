"""Tutoring 工作流编排：Planner → (Diagnoser) → Evidence → LearnerModel → re-plan。

闭环：
  Learning Goal → KC Graph → Learner State → Planner → Selected KC → Teaching Action
  → Tutor → Learner Response → Diagnoser → Structured Evidence → LearnerModel Update
  → Re-plan → Learning Map Update
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy
from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_graph_service import CourseGraphService
from edu_agent.workflows.tutoring.agents import Diagnoser, Planner, Tutor
from edu_agent.workflows.tutoring.schemas import (
    Diagnosis,
    PlannerDecision,
    TutorRequest,
    TutorResponse,
)

logger = logging.getLogger("edu_agent.tutoring.workflow")


class TutoringWorkflow:
    """单课程、单用户的多智能体自适应教学闭环。

    使用统一 active graph（动态 persisted KCGraph 优先，回退内置 course）。
    任何 ``kc_id`` 必须存在于 active graph 中，否则视为非法（调用方应返回 400/404）。
    """

    def __init__(
        self,
        course_id: str,
        learner_model: LearnerModelService,
        user_id: Optional[str] = None,
    ) -> None:
        self.course_id = course_id
        self.learner_model = learner_model
        self.graph_service = CourseGraphService(self.learner_model._repo)
        active = self.graph_service.load_active_graph(user_id, course_id) if user_id else None
        if active is None:
            active = self.graph_service.load_active_graph(None, course_id)
        if active is None:
            raise ValueError(f"course not found: {course_id}")
        self.course = active.course
        self.graph_source = active.graph_source
        self.goal_kcs = [c.kc_id for c in self.course.components]
        self.planner = Planner(self.course, goal_kcs=self.goal_kcs)
        self.tutor = Tutor(self.course)
        self.diagnoser = Diagnoser(self.course)

    def _require_kc(self, kc_id: str) -> None:
        if kc_id not in {c.kc_id for c in self.course.components}:
            raise ValueError(
                f"kc_id '{kc_id}' not found in active graph for course '{self.course_id}' "
                f"(graph_source={self.graph_source})"
            )

    # -- 读取 learner state（统一接口） ------------------------------------
    def _snapshot(self, user_id: str) -> Dict[str, Any]:
        bundle = self.learner_model.build_bundle(user_id, self.course_id)
        knowledge = bundle.course_state.knowledge
        mastery_map: Dict[str, Optional[float]] = {}
        conf_map: Dict[str, Optional[float]] = {}
        misconception_map: Dict[str, List[str]] = {}
        recent_error_map: Dict[str, bool] = {}
        for item in knowledge:
            mastery_map[item.kc_id] = item.mastery
            conf_map[item.kc_id] = item.confidence
            # misconceptions / recent evidence 现在统一从 learning_events 派生
        for kc_id in (c.kc_id for c in self.course.components):
            if kc_id not in mastery_map:
                mastery_map[kc_id] = None
                conf_map[kc_id] = None
        # 从事件派生 misconceptions / recent_error
        events = self.learner_model.get_events(user_id, self.course_id, limit=200)
        for ev in events:
            kc = ev.get("kc_id") or (ev.get("payload") or {}).get("kc_id")
            if not kc:
                continue
            payload = ev.get("payload") or {}
            mc = payload.get("misconceptions") or []
            if mc:
                misconception_map.setdefault(kc, [])
                for m in mc:
                    if m not in misconception_map[kc]:
                        misconception_map[kc].append(m)
            if payload.get("correctness") == "incorrect":
                recent_error_map[kc] = True
        return {
            "mastery_map": mastery_map,
            "conf_map": conf_map,
            "misconception_map": misconception_map,
            "recent_error_map": recent_error_map,
        }

    # -- 开始一轮教学（无 message） ---------------------------------------
    def start_turn(self, user_id: str, req: TutorRequest) -> TutorResponse:
        if req.kc_id:
            self._require_kc(req.kc_id)
        snap = self._snapshot(user_id)
        decision = self.planner.plan(
            snap["mastery_map"],
            snap["misconception_map"],
            snap["recent_error_map"],
            current_kc=req.kc_id or None,
        )
        return self.tutor.teach(decision, misconception_list=snap["misconception_map"].get(decision.selected_kc))

    # -- 处理用户回复 ------------------------------------------------------
    def answer_turn(self, user_id: str, req: TutorRequest) -> TutorResponse:
        kc_id = req.kc_id
        if kc_id:
            self._require_kc(kc_id)
        # 1) Diagnoser
        diagnosis = self.diagnoser.diagnose(kc_id, req.message or "")

        # 2) 结构化 Evidence → LearnerModel 更新（确定性）
        before = self._snapshot(user_id)
        self.learner_model.apply_event(
            {
                "event_type": "TUTOR_EVIDENCE",
                "user_id": user_id,
                "course_id": self.course_id,
                "kc_id": kc_id,
                "source": "tutor",
                "payload": {
                    "kc_id": kc_id,
                    "kc_name": self.course.kc_by_id(kc_id).title if self.course.kc_by_id(kc_id) else kc_id,
                    "correctness": diagnosis.correctness,
                    "difficulty": diagnosis.difficulty,
                    "hint_level": diagnosis.hint_level,
                    "confidence": diagnosis.confidence,
                    "misconceptions": diagnosis.misconceptions,
                    "evidence_type": "tutor_turn",
                    "teaching_action": "",
                },
            }
        )

        # 3) Re-plan（基于更新后的 state）
        after = self._snapshot(user_id)
        policy = HeuristicAdaptivePolicy(self.course, goal_kcs=self.goal_kcs)
        path = policy.recommended_path(
            after["mastery_map"], after["misconception_map"], after["recent_error_map"],
            current_kc=kc_id,
        )
        next_kc = path[0] if path else kc_id

        # 4) 生成 Tutor 反馈（基于 diagnosis）
        decision = PlannerDecision(
            selected_kc=next_kc,
            teaching_action=self._next_action(diagnosis),
            difficulty=diagnosis.difficulty,
            reason_codes=[]
            + (["RECENT_SUCCESS"] if diagnosis.correctness == "correct" else [])
            + (["RECENT_ERROR"] if diagnosis.correctness == "incorrect" else [])
            + (["MISCONCEPTION_DETECTED"] if diagnosis.misconceptions else []),
        )
        response = self.tutor.teach(decision, req.message, misconception_list=diagnosis.misconceptions)
        response.learner_state_changed = True
        response.learning_map_changed = True
        response.mastery = after["mastery_map"].get(next_kc)
        response.confidence = after["conf_map"].get(next_kc)
        response.next_recommended_kc = next_kc

        # 结构化日志（不记录敏感内容 / 思维链）
        logger.info(
            "tutor_turn user=%s course=%s kc=%s correctness=%s mastery_before=%s mastery_after=%s",
            user_id, self.course_id, kc_id, diagnosis.correctness,
            before["mastery_map"].get(kc_id), after["mastery_map"].get(kc_id),
        )
        return response

    def _next_action(self, diagnosis: Diagnosis):
        from edu_agent.workflows.tutoring.schemas import TeachingAction

        if diagnosis.misconceptions:
            return TeachingAction.COMPARE
        if diagnosis.correctness == "incorrect":
            return TeachingAction.HINT
        if diagnosis.correctness == "correct":
            return TeachingAction.PRACTICE
        return TeachingAction.PROBE
