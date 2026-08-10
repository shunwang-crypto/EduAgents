"""事件 → 证据 规则表。

新增/修正：
- CHECK_UNDERSTANDING_RESPONSE / SELF_EXPLANATION_SUBMITTED：知识 + 能力证据（medium）
- FEEDBACK_GIVEN：偏好有效性证据（按 delivery_mode）
- 不再用「为什么/区别」等粗糙关键词规则制造 misconception（交给 semantic_classifier 高确定规则）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from edu_agent.learner_model.evidence.schemas import EvidenceStrength, SourceReliability

EVENT_TYPES: List[str] = [
    "SESSION_STARTED", "SESSION_ENDED", "COURSE_OPENED",
    "GOAL_CREATED", "GOAL_UPDATED", "GOAL_COMPLETED", "GOAL_CANCELLED",
    "TOPIC_STARTED", "TOPIC_COMPLETED", "TOPIC_REVISITED",
    "QUESTION_ASKED", "EDUCATIONAL_QUESTION_ASKED",
    "EXPLANATION_REQUESTED", "EXPLANATION_DELIVERED",
    "RE_EXPLAIN_REQUESTED", "EXAMPLE_REQUESTED", "ANALOGY_REQUESTED",
    "SIMPLIFICATION_REQUESTED", "DEEPER_EXPLANATION_REQUESTED",
    "PREREQUISITE_REVIEWED", "RESOURCE_OPENED", "RESOURCE_COMPLETED",
    "PLAN_CREATED", "PLAN_UPDATED", "PLAN_STEP_STARTED", "PLAN_STEP_COMPLETED",
    "SELF_REPORTED_UNDERSTANDING", "SELF_REPORTED_CONFUSION",
    "USER_EXPLICIT_PREFERENCE", "USER_EXPLICIT_PROFILE_FACT",
    "TEACHING_MODE_SWITCHED", "FEEDBACK_GIVEN", "PROFILE_FACT_DELETED",
    # 教学理解检查（非 Quiz）
    "CHECK_UNDERSTANDING_RESPONSE", "SELF_EXPLANATION_SUBMITTED",
    "CONCEPT_COMPARISON_RESPONSE",
]

# (evidence_strength, source, meaningful_for_profile)
_EVENT_META: Dict[str, Tuple[EvidenceStrength, SourceReliability, bool]] = {
    "SESSION_STARTED": ("weak", "SYSTEM_OBSERVATION", False),
    "SESSION_ENDED": ("weak", "SYSTEM_OBSERVATION", False),
    "COURSE_OPENED": ("weak", "SYSTEM_OBSERVATION", False),
    "GOAL_CREATED": ("medium", "USER_EXPLICIT", True),
    "GOAL_UPDATED": ("medium", "USER_EXPLICIT", True),
    "GOAL_COMPLETED": ("strong", "USER_EXPLICIT", True),
    "GOAL_CANCELLED": ("medium", "USER_EXPLICIT", True),
    "TOPIC_STARTED": ("weak", "SYSTEM_OBSERVATION", True),
    "TOPIC_COMPLETED": ("medium", "TEACHING_INTERACTION", True),
    "TOPIC_REVISITED": ("weak", "BEHAVIOR_INFERENCE", True),
    "QUESTION_ASKED": ("weak", "SYSTEM_OBSERVATION", False),
    "EDUCATIONAL_QUESTION_ASKED": ("weak", "TEACHING_INTERACTION", True),
    "EXPLANATION_REQUESTED": ("weak", "TEACHING_INTERACTION", True),
    "EXPLANATION_DELIVERED": ("weak", "SYSTEM_OBSERVATION", True),
    "RE_EXPLAIN_REQUESTED": ("medium", "TEACHING_INTERACTION", True),
    "EXAMPLE_REQUESTED": ("medium", "TEACHING_INTERACTION", True),
    "ANALOGY_REQUESTED": ("medium", "TEACHING_INTERACTION", True),
    "SIMPLIFICATION_REQUESTED": ("medium", "TEACHING_INTERACTION", True),
    "DEEPER_EXPLANATION_REQUESTED": ("weak", "TEACHING_INTERACTION", True),
    "PREREQUISITE_REVIEWED": ("weak", "SYSTEM_OBSERVATION", True),
    "RESOURCE_OPENED": ("weak", "SYSTEM_OBSERVATION", False),
    "RESOURCE_COMPLETED": ("weak", "SYSTEM_OBSERVATION", True),
    "PLAN_CREATED": ("medium", "SYSTEM_OBSERVATION", True),
    "PLAN_UPDATED": ("medium", "SYSTEM_OBSERVATION", True),
    "PLAN_STEP_STARTED": ("weak", "SYSTEM_OBSERVATION", True),
    "PLAN_STEP_COMPLETED": ("medium", "TEACHING_INTERACTION", True),
    "SELF_REPORTED_UNDERSTANDING": ("weak", "USER_EXPLICIT", True),
    "SELF_REPORTED_CONFUSION": ("weak", "USER_EXPLICIT", True),
    "USER_EXPLICIT_PREFERENCE": ("strong", "USER_EXPLICIT", True),
    "USER_EXPLICIT_PROFILE_FACT": ("strong", "USER_EXPLICIT", True),
    "TEACHING_MODE_SWITCHED": ("weak", "TEACHING_INTERACTION", False),
    "FEEDBACK_GIVEN": ("medium", "USER_EXPLICIT", True),
    "PROFILE_FACT_DELETED": ("strong", "USER_EXPLICIT", True),
    # 教学理解检查（medium，用户自述）
    "CHECK_UNDERSTANDING_RESPONSE": ("medium", "USER_EXPLICIT", True),
    "SELF_EXPLANATION_SUBMITTED": ("medium", "USER_EXPLICIT", True),
    "CONCEPT_COMPARISON_RESPONSE": ("medium", "USER_EXPLICIT", True),
}


def _kc(event) -> str:
    return event.kc_id or (event.payload or {}).get("kc_id") or ""


def _topic(event) -> str:
    payload = event.payload or {}
    return payload.get("topic") or payload.get("kc_name") or event.kc_id or ""


def rules_for(event) -> List[Tuple[str, str, str, bool]]:
    """按事件类型返回规则 [(entity_type, direction, entity_key, meaningful)]。"""
    t = event.event_type
    payload = event.payload or {}
    kc = _kc(event)
    topic = _topic(event)

    if t in ("EXPLANATION_DELIVERED", "RESOURCE_COMPLETED", "TOPIC_COMPLETED", "PLAN_STEP_COMPLETED"):
        return [("knowledge", "neutral", kc, True)] if kc else []
    if t in ("EXPLANATION_REQUESTED", "TOPIC_STARTED", "TOPIC_REVISITED", "PREREQUISITE_REVIEWED"):
        return [("knowledge", "neutral", kc or topic, True)] if (kc or topic) else []
    if t == "SELF_REPORTED_UNDERSTANDING":
        return [("knowledge", "pos", kc, True)] if kc else []
    if t == "SELF_REPORTED_CONFUSION":
        return [("knowledge", "neg", kc, True)] if kc else []
    if t in ("RE_EXPLAIN_REQUESTED", "SIMPLIFICATION_REQUESTED"):
        out = []
        if kc:
            out.append(("knowledge", "neg", kc, True))
        if t == "SIMPLIFICATION_REQUESTED":
            out.append(("preference", "pos", "step_by_step", True))
        return out
    if t == "EXAMPLE_REQUESTED":
        out = [("preference", "pos", "worked_example", True)]
        if kc:
            out.append(("knowledge", "neutral", kc, True))
        return out
    if t == "ANALOGY_REQUESTED":
        return [("preference", "pos", "analogy", True)]
    if t == "DEEPER_EXPLANATION_REQUESTED":
        return [("preference", "pos", "concept_first", True)]
    if t == "EDUCATIONAL_QUESTION_ASKED":
        return [("behavior", "neutral", topic, True)] if topic else []
    if t == "USER_EXPLICIT_PREFERENCE":
        key = payload.get("preference_key") or ""
        direction = payload.get("direction", "pos")
        return [("preference", direction, key, True)] if key else []
    if t == "USER_EXPLICIT_PROFILE_FACT":
        key = payload.get("fact_key") or ""
        return [("profile_fact", "pos", key, True)] if key else []
    if t == "PROFILE_FACT_DELETED":
        key = payload.get("fact_key") or ""
        return [("profile_fact", "neg", key, True)] if key else []
    if t in ("GOAL_CREATED", "GOAL_UPDATED", "GOAL_COMPLETED", "GOAL_CANCELLED"):
        goal_id = payload.get("goal_id") or ""
        return [("goal", "neutral", goal_id, True)] if goal_id else []
    # 教学理解检查：知识证据（medium），能力/误解由 semantic_classifier 处理
    if t == "CHECK_UNDERSTANDING_RESPONSE":
        out = [("knowledge", "pos", kc, True)] if kc else []
        return out
    if t == "SELF_EXPLANATION_SUBMITTED":
        return [("knowledge", "neutral", kc, True)] if kc else []
    # 反馈：按 delivery_mode 调整偏好有效性（不能直接改 mastery）
    if t == "FEEDBACK_GIVEN":
        direction = payload.get("direction", "positive")
        mode = payload.get("delivery_mode") or ""
        pref_key = _feedback_pref_key(mode)
        if pref_key:
            return [("preference", "pos" if direction == "positive" else "neg", pref_key, True)]
        return []
    return []


def _feedback_pref_key(delivery_mode: str) -> str:
    """FEEDBACK_GIVEN 的 delivery_mode → 对应偏好键。"""
    return {
        "worked_example": "worked_example",
        "analogy": "analogy",
        "code": "code_example",
        "diagram": "diagram",
        "step_by_step": "step_by_step",
        "concept_first": "concept_first",
    }.get(delivery_mode, "")


def event_meta(event_type: str) -> Tuple[EvidenceStrength, SourceReliability, bool]:
    return _EVENT_META.get(event_type, ("weak", "SYSTEM_OBSERVATION", False))
