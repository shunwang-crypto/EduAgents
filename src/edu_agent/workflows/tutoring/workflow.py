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
    PrerequisiteNotMet,
    TutorRequest,
    TutorResponse,
)

logger = logging.getLogger("edu_agent.tutoring.workflow")

# P2-1：recent_error 只看最近 N 条有效 tutoring evidence。
_RECENT_EVIDENCE_N = 3


def _recent_tutoring_evidence(events: List[dict]) -> Dict[str, List[dict]]:
    """按 kc_id 聚合最近 N 条有效 tutoring evidence（时间降序）。

    events 已由 repository 按时间倒序返回；这里过滤出 TUTOR_EVIDENCE / tutor_turn，
    并为每个 KC 保留最近的 ``_RECENT_EVIDENCE_N`` 条。
    """
    per_kc: Dict[str, List[dict]] = {}
    for ev in events:
        payload = ev.get("payload") or {}
        if payload.get("evidence_type") != "tutor_turn" and ev.get("event_type") != "TUTOR_EVIDENCE":
            continue
        kc = ev.get("kc_id") or payload.get("kc_id")
        if not kc:
            continue
        if kc not in per_kc:
            per_kc[kc] = []
        if len(per_kc[kc]) >= _RECENT_EVIDENCE_N:
            continue
        per_kc[kc].append(
            {
                "correctness": payload.get("correctness"),
                "difficulty": payload.get("difficulty"),
                "teaching_action": payload.get("teaching_action"),
                "timestamp": ev.get("timestamp"),
            }
        )
    return per_kc


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _new_turn_id() -> str:
    import uuid

    return f"TURN-{uuid.uuid4().hex[:12]}"


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
        # P2-1：recent_error 必须真的“recent”。
        # 只取每个 KC 最近 N 条有效 tutoring evidence；只有“最新一条”为 incorrect 才标
        # RECENT_ERROR。若最新表现已连续正确，旧错误不再永久影响。
        for kc_id, recent in _recent_tutoring_evidence(events).items():
            if recent and recent[0].get("correctness") == "incorrect":
                recent_error_map[kc_id] = True
        return {
            "mastery_map": mastery_map,
            "conf_map": conf_map,
            "misconception_map": misconception_map,
            "recent_error_map": recent_error_map,
        }

    # -- 锁定判定（P1-3：不能只靠 UI） -------------------------------------
    def _assert_unlocked(self, kc_id: str, mastery_map: Dict[str, Optional[float]]) -> None:
        """Locked KC 不允许开始 Tutor。抛出结构化异常供上层返回 409/400。"""
        if not self.planner.policy.is_locked(kc_id, mastery_map):
            return
        prereqs = self.planner.policy.prereq_status(kc_id, mastery_map)
        raise PrerequisiteNotMet(
            kc_id=kc_id,
            prerequisites=[p["kc_id"] for p in prereqs if p["state"] != "mastered"],
        )

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
        kc_id = decision.selected_kc
        # P1-3：锁定节点不允许开始 Tutor（后端防御，不能只依赖 UI disabled）。
        self._assert_unlocked(kc_id, snap["mastery_map"])
        response = self.tutor.teach(decision, misconception_list=snap["misconception_map"].get(kc_id))

        # P1-5：最小 Tutor Turn Context。开始一轮教学时登记 turn_id + 教学上下文
        # （teaching_action / question / rubric），供 answer_turn 的 Diagnoser 使用。
        turn_id = _new_turn_id()
        self._record_turn_context(user_id, turn_id, kc_id, response)
        response.turn_id = turn_id
        return response

    def _record_turn_context(
        self, user_id: str, turn_id: str, kc_id: str, response: TutorResponse
    ) -> None:
        """把当前轮的教学上下文持久化为事件（最小 session，无独立表）。"""
        self.learner_model.record_event(
            {
                "event_type": "TUTOR_TURN_STARTED",
                "user_id": user_id,
                "course_id": self.course_id,
                "kc_id": kc_id,
                "source": "tutor",
                "payload": {
                    "turn_id": turn_id,
                    "kc_id": kc_id,
                    "teaching_action": response.teaching_action.value,
                    "question": response.message,
                    # 简化 rubric：复用教学消息作为评估提示（无独立大型 rubric 系统）。
                    "evaluation_rubric": response.message,
                    "difficulty": response.teaching_action.value,
                    "created_at": _now_iso(),
                },
            }
        )

    def _find_turn_context(self, user_id: str, turn_id: str) -> Optional[dict]:
        """按 turn_id 查找开始轮登记的教学上下文（question / teaching_action / rubric）。"""
        if not turn_id:
            return None
        events = self.learner_model.get_events(user_id, self.course_id, limit=100)
        for ev in events:
            payload = ev.get("payload") or {}
            if ev.get("event_type") == "TUTOR_TURN_STARTED" and payload.get("turn_id") == turn_id:
                return payload
        return None

    # -- 处理用户回复 ------------------------------------------------------
    def answer_turn(self, user_id: str, req: TutorRequest) -> TutorResponse:
        kc_id = req.kc_id
        if kc_id:
            self._require_kc(kc_id)
        before = self._snapshot(user_id)

        # P1-5：最小 Turn Context → 把“原问题 / 教学动作 / 评估提示”交给 Diagnoser。
        turn_ctx = self._find_turn_context(user_id, req.turn_id) if req.turn_id else None
        teaching_action = (turn_ctx or {}).get("teaching_action") or ""
        question = (turn_ctx or {}).get("question") or ""
        rubric = (turn_ctx or {}).get("evaluation_rubric") or question

        # 1) Diagnoser：KC 信息 + 原问题 + 教学动作 + rubric + 学习者回答。
        diagnosis = self.diagnoser.diagnose(
            kc_id,
            req.message or "",
            expected_answer_hint=question or rubric or None,
            teaching_action=teaching_action,
        )

        # 2) 结构化 Evidence → LearnerModel 更新（确定性）。
        # P1-6 / 防刷：同 turn_id 只生成一次 effective evidence——用确定性的
        # event_id = EV-TURN-{turn_id}，insert_event 幂等即天然去重。
        event_id = f"EV-TURN-{req.turn_id}" if req.turn_id else None
        self.learner_model.apply_event(
            {
                **({"event_id": event_id} if event_id else {}),
                "event_type": "TUTOR_EVIDENCE",
                "user_id": user_id,
                "course_id": self.course_id,
                "kc_id": kc_id,
                "source": "tutor",
                "evidence_strength": diagnosis.evidence_strength,
                "payload": {
                    "kc_id": kc_id,
                    "kc_name": self.course.kc_by_id(kc_id).title if self.course.kc_by_id(kc_id) else kc_id,
                    "correctness": diagnosis.correctness,
                    "difficulty": diagnosis.difficulty,
                    "hint_level": diagnosis.hint_level,
                    "confidence": diagnosis.confidence,
                    "evidence_strength": diagnosis.evidence_strength,
                    "misconceptions": diagnosis.misconceptions,
                    "evidence_type": "tutor_turn",
                    "teaching_action": teaching_action,
                    "turn_id": req.turn_id or "",
                },
            }
        )

        # 3) Re-plan（基于更新后的 state）——只用于“下一步推荐”，不改变当前 KC。
        after = self._snapshot(user_id)
        policy = HeuristicAdaptivePolicy(self.course, goal_kcs=self.goal_kcs)
        path = policy.recommended_path(
            after["mastery_map"], after["misconception_map"], after["recent_error_map"],
            current_kc=kc_id,
        )
        next_kc = path[0] if path else None

        # 4) 生成 Tutor 反馈（基于 diagnosis）。
        # P1-4：response.kc_id 保持“当前 KC”，next_recommended_kc 单独返回。
        feedback_decision = PlannerDecision(
            selected_kc=kc_id,
            teaching_action=self._next_action(diagnosis),
            difficulty=diagnosis.difficulty,
            reason_codes=[]
            + (["RECENT_SUCCESS"] if diagnosis.correctness == "correct" else [])
            + (["RECENT_ERROR"] if diagnosis.correctness == "incorrect" else [])
            + (["MISCONCEPTION_DETECTED"] if diagnosis.misconceptions else []),
        )
        response = self.tutor.teach(feedback_decision, req.message, misconception_list=diagnosis.misconceptions)
        response.learner_state_changed = True
        response.learning_map_changed = True
        # current KC 的 mastery 变化才是有意义的“结果”。
        response.mastery = after["mastery_map"].get(kc_id)
        response.confidence = after["conf_map"].get(kc_id)
        response.next_recommended_kc = next_kc
        response.turn_id = req.turn_id or None

        # 结构化日志（不记录敏感内容 / 思维链）
        logger.info(
            "tutor_turn user=%s course=%s kc=%s correctness=%s evidence_strength=%s "
            "mastery_before=%s mastery_after=%s next_recommended=%s",
            user_id, self.course_id, kc_id, diagnosis.correctness,
            diagnosis.evidence_strength,
            before["mastery_map"].get(kc_id), after["mastery_map"].get(kc_id), next_kc,
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
