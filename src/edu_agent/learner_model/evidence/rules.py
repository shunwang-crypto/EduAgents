"""事件 → 证据 规则表。

定义每个事件类型：
- 默认证据强度（weak/medium/strong）
- 可靠度来源
- 是否 meaningful_for_profile（是否值得写回长期画像）
- 可能产生的证据（entity_type / direction / entity_key 提取方式）

原则：
- EXPLANATION_DELIVERED / 浏览类事件只产生「曝光」证据，绝不改 mastery。
- SELF_REPORTED_UNDERSTANDING 是弱证据：只微调 confidence，不跳 mastery。
- 用户明确声明（USER_EXPLICIT_*）是强证据，优先于推断。
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
]

# 每个事件类型默认元数据
_EVENT_META: Dict[str, Tuple[EvidenceStrength, SourceReliability, bool]] = {
    # strength, source, meaningful_for_profile
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
    "EXAMPLE_REQUESTED": ("weak", "TEACHING_INTERACTION", True),
    "ANALOGY_REQUESTED": ("weak", "TEACHING_INTERACTION", True),
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
}

# 各事件 → 证据（entity_type, direction, entity_key 提取函数）
def _kc(event) -> Optional[str]:
    return event.kc_id or (event.payload or {}).get("kc_id") or ""


def _topic(event) -> Optional[str]:
    payload = event.payload or {}
    return payload.get("topic") or payload.get("kc_name") or event.kc_id or ""


def _pref_key(payload) -> Optional[str]:
    return payload.get("preference_key") or ""


def _fact_key(payload) -> Optional[str]:
    return payload.get("fact_key") or ""


# 返回 [(entity_type, direction, entity_key, meaningful)]
def rules_for(event) -> List[Tuple[str, str, str, bool]]:
    """按事件类型返回规则（key 为空表示该规则不产出证据）。"""
    t = event.event_type
    payload = event.payload or {}
    kc = _kc(event)
    topic = _topic(event)

    if t in ("EXPLANATION_DELIVERED", "RESOURCE_COMPLETED", "TOPIC_COMPLETED", "PLAN_STEP_COMPLETED"):
        # 曝光证据：只更新时间/计数，不改 mastery
        return [("knowledge", "neutral", kc, True)] if kc else []
    if t in ("EXPLANATION_REQUESTED", "TOPIC_STARTED", "TOPIC_REVISITED", "PREREQUISITE_REVIEWED"):
        return [("knowledge", "neutral", kc or topic, True)] if (kc or topic) else []
    if t == "SELF_REPORTED_UNDERSTANDING":
        # 弱证据：只微调 confidence 正向，不跳 mastery
        return [("knowledge", "pos", kc, True)] if kc else []
    if t == "SELF_REPORTED_CONFUSION":
        return [("knowledge", "neg", kc, True)] if kc else []
    if t in ("RE_EXPLAIN_REQUESTED", "SIMPLIFICATION_REQUESTED"):
        out = []
        if kc:
            out.append(("knowledge", "neg", kc, True))  # 需要辅导的信号
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
        key = _pref_key(payload)
        direction = payload.get("direction", "pos")
        return [("preference", direction, key, True)] if key else []
    if t == "USER_EXPLICIT_PROFILE_FACT":
        key = _fact_key(payload)
        return [("profile_fact", "pos", key, True)] if key else []
    if t == "PROFILE_FACT_DELETED":
        key = _fact_key(payload)
        return [("profile_fact", "neg", key, True)] if key else []
    if t in ("GOAL_CREATED", "GOAL_UPDATED", "GOAL_COMPLETED", "GOAL_CANCELLED"):
        goal_id = payload.get("goal_id") or ""
        return [("goal", "neutral", goal_id, True)] if goal_id else []
    return []


def event_meta(event_type: str) -> Tuple[EvidenceStrength, SourceReliability, bool]:
    return _EVENT_META.get(event_type, ("weak", "SYSTEM_OBSERVATION", False))
