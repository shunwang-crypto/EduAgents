"""LearnerStateAdapter：合作伙伴原始 JSON → 内部 LearnerState 模型。

设计：
- 业务代码禁止直接访问 profile["student_model"]["pace_factor"] 这类原始字段。
- 合作伙伴修改字段时，只改本文件。
- 解析是宽容的：缺失字段回退默认值，不抛异常（保持业务可用）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from edu_agent.integrations.learner_state.schemas import (
    AbilityItem,
    BehaviorState,
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
    KnowledgeItem,
    Misconception,
    ModeScore,
    Preferences,
    Profile,
    SemanticMemoryItem,
)


def _pick(d: Any, *paths: str, default: Any = None) -> Any:
    """按多个备选路径取值：依次尝试每条路径，返回第一个非 None 结果。

    - 每条路径支持点号嵌套，如 "profile.user_id"。
    - 返回值可能为 0 / False / ""，这些不被当作"缺失"（只跳过 None）。
    """
    for path in paths:
        cur = d
        keys = str(path).split(".")
        for key in keys:
            if isinstance(cur, dict):
                cur = cur.get(key)
            elif isinstance(cur, list) and key.isdigit():
                index = int(key)
                cur = cur[index] if index < len(cur) else None
            else:
                cur = None
                break
        if cur is not None:
            return cur
    return default


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Global State 解析
# ---------------------------------------------------------------------------


def parse_profile(raw: Any) -> Profile:
    raw = raw if isinstance(raw, dict) else {}
    return Profile(
        user_id=str(_pick(raw, "user_id", default="") or ""),
        display_name=str(_pick(raw, "display_name", "displayName", default="") or ""),
        education_level=str(_pick(raw, "education_level", "educationLevel", default="") or ""),
        language=str(_pick(raw, "language", default="zh") or "zh"),
        background=str(_pick(raw, "background", default="") or ""),
    )


def _parse_mode_effectiveness(raw: Any) -> Dict[str, ModeScore]:
    result: Dict[str, ModeScore] = {}
    if not isinstance(raw, dict):
        return result
    for mode, value in raw.items():
        if isinstance(value, dict):
            result[mode] = ModeScore(
                score=_as_float(value.get("score"), 0.0),
                confidence=_as_float(value.get("confidence"), 0.0),
                sample_size=_as_int(value.get("sample_size", value.get("sampleSize")), 0),
            )
        elif isinstance(value, (int, float)):
            result[mode] = ModeScore(score=float(value), confidence=0.5, sample_size=1)
    return result


def parse_preferences(raw: Any) -> Preferences:
    raw = raw if isinstance(raw, dict) else {}
    mode_effectiveness_raw = _pick(
        raw, "mode_effectiveness", "modeEffectiveness", "mode_scores", default={}
    )
    return Preferences(
        preferred_mode=str(
            _pick(raw, "preferred_mode", "preferredMode", default="") or ""
        ),
        learning_style_distribution={
            str(k): _as_float(v, 0.0)
            for k, v in (_pick(raw, "learning_style_distribution", "learningStyleDistribution", default={}) or {}).items()
        },
        mode_effectiveness=_parse_mode_effectiveness(mode_effectiveness_raw),
        pace_factor=_as_float(_pick(raw, "pace_factor", "paceFactor", default=1.0), 1.0) or 1.0,
        scaffold_preference=_as_float(
            _pick(raw, "scaffold_preference", "scaffoldPreference", default=0.5), 0.5
        ),
    )


def parse_goals(raw: Any) -> List[Goal]:
    goals: List[Goal] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        target_kcs_raw = _pick(item, "target_kcs", "targetKcs", "kcs", default=[])
        goals.append(
            Goal(
                goal_id=str(_pick(item, "goal_id", "goalId", default="") or ""),
                course_id=str(_pick(item, "course_id", "courseId", default="") or ""),
                goal_name=str(_pick(item, "goal_name", "goalName", "name", default="") or ""),
                target=str(_pick(item, "target", default="") or ""),
                priority=_as_int(_pick(item, "priority", default=1), 1) or 1,
                status=str(_pick(item, "status", default="active") or "active"),
                progress=_as_float(_pick(item, "progress", default=0.0), 0.0),
                target_kcs=[str(k) for k in _as_list(target_kcs_raw)],
            )
        )
    return goals


def parse_semantic_memory(raw: Any) -> List[SemanticMemoryItem]:
    items: List[SemanticMemoryItem] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            items.append(
                SemanticMemoryItem(
                    content=str(item.get("content", "") or ""),
                    tags=[str(t) for t in _as_list(item.get("tags", []))],
                    created_at=str(item.get("created_at", item.get("createdAt", "")) or ""),
                )
            )
        elif isinstance(item, str):
            items.append(SemanticMemoryItem(content=item))
    return items


def parse_global_state(raw: Any) -> GlobalLearnerState:
    """容忍多种常见包装：{profile:...} / {student:...} / 直接平铺。"""
    if not isinstance(raw, dict):
        return GlobalLearnerState()
    profile_raw = _pick(raw, "profile", "student_profile", "studentProfile", "student", default={})
    prefs_raw = _pick(raw, "preferences", "prefs", default={})
    goals_raw = _pick(raw, "goals", "active_goals", "activeGoals", default=[])
    memory_raw = _pick(raw, "semantic_memory", "semanticMemory", "memory", default=[])
    return GlobalLearnerState(
        profile=parse_profile(profile_raw),
        preferences=parse_preferences(prefs_raw),
        goals=parse_goals(goals_raw),
        semantic_memory=parse_semantic_memory(memory_raw),
    )


# ---------------------------------------------------------------------------
# Course State 解析
# ---------------------------------------------------------------------------


def parse_knowledge(raw: Any) -> List[KnowledgeItem]:
    items: List[KnowledgeItem] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        # 兼容两种字段形态：mastery/.p、confidence/.conf、kc_id/.id/.knowledge_point_id
        items.append(
            KnowledgeItem(
                kc_id=str(
                    _pick(item, "kc_id", "kcId", "id", "knowledge_point_id", "knowledgePointId", default="")
                    or ""
                ),
                name=str(_pick(item, "name", "title", default="") or ""),
                mastery=_as_float(_pick(item, "mastery", "p", "value", default=0.0), 0.0),
                confidence=_as_float(_pick(item, "confidence", "conf", default=0.0), 0.0),
                status=str(_pick(item, "status", default="unknown") or "unknown"),
                trend=str(_pick(item, "trend", default="unknown") or "unknown"),
                evidence_count=_as_int(
                    _pick(item, "evidence_count", "evidenceCount", "count", default=0), 0
                ),
                last_evidence_at=_pick(
                    item, "last_evidence_at", "lastEvidenceAt", default=None
                ),
                is_estimated=_as_bool(
                    _pick(item, "is_estimated", "isEstimated", default=False), False
                ),
            )
        )
    return items


def parse_abilities(raw: Any) -> Dict[str, AbilityItem]:
    result: Dict[str, AbilityItem] = {}
    if not isinstance(raw, dict):
        return result
    for ability, value in raw.items():
        if isinstance(value, dict):
            result[str(ability)] = AbilityItem(
                score=_as_float(value.get("score", 0.0), 0.0),
                confidence=_as_float(value.get("confidence", 0.0), 0.0),
                trend=str(value.get("trend", "unknown") or "unknown"),
                evidence_count=_as_int(value.get("evidence_count", value.get("evidenceCount", 0)), 0),
            )
        elif isinstance(value, (int, float)):
            result[str(ability)] = AbilityItem(score=float(value), confidence=0.5, evidence_count=1)
    return result


def parse_misconceptions(raw: Any) -> List[Misconception]:
    items: List[Misconception] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        items.append(
            Misconception(
                misconception_id=str(
                    _pick(item, "misconception_id", "misconceptionId", "id", default="") or ""
                ),
                kc_id=str(_pick(item, "kc_id", "kcId", default="") or ""),
                type=str(_pick(item, "type", default="conceptual_confusion") or "conceptual_confusion"),
                description=str(item.get("description", "") or ""),
                severity=_as_float(item.get("severity", 0.5), 0.5),
                confidence=_as_float(item.get("confidence", 0.5), 0.5),
                occurrence_count=_as_int(
                    item.get("occurrence_count", item.get("occurrenceCount", 0)), 0
                ),
                status=str(item.get("status", "active") or "active"),
                first_seen_at=item.get("first_seen_at", item.get("firstSeenAt")),
                last_seen_at=item.get("last_seen_at", item.get("lastSeenAt")),
            )
        )
    return items


def parse_behavior(raw: Any) -> BehaviorState:
    raw = raw if isinstance(raw, dict) else {}
    return BehaviorState(
        activity_count_30d=_as_int(
            _pick(raw, "activity_count_30d", "activityCount30d", "activity_count", default=0), 0
        ),
        streak_days=_as_int(_pick(raw, "streak_days", "streakDays", default=0), 0),
        average_session_minutes=_as_float(
            _pick(raw, "average_session_minutes", "averageSessionMinutes", default=0.0), 0.0
        ),
        recent_topics=[str(t) for t in _as_list(_pick(raw, "recent_topics", "recentTopics", default=[]))],
        frequent_revisited_topics=[
            str(t) for t in _as_list(_pick(raw, "frequent_revisited_topics", "frequentRevisitedTopics", default=[]))
        ],
    )


def parse_course_state(raw: Any, user_id: str = "", course_id: str = "") -> CourseLearnerState:
    """把合作伙伴课程状态 JSON 转成内部模型。

    兼容：
    - 直接是 state 对象；
    - 或包在 {"data": {...}} / {"state": {...}} / {"learner_state": {...}} 里。
    """
    if not isinstance(raw, dict):
        raw = {}
    if "data" in raw and isinstance(raw["data"], dict):
        raw = raw["data"]
    if "state" in raw and isinstance(raw["state"], dict):
        raw = raw["state"]
    if "learner_state" in raw and isinstance(raw["learner_state"], dict):
        raw = raw["learner_state"]

    knowledge_raw = _pick(raw, "knowledge", "knowledge_state", "knowledgeState", "kcs", default=[])
    metadata = dict(_pick(raw, "metadata", default={}) or {})
    if isinstance(metadata, dict):
        for key in ("schema_version", "schemaVersion", "state_version", "stateVersion", "updated_at", "updatedAt"):
            val = _pick(raw, key, default=None)
            if val is not None:
                metadata.setdefault(key, val)

    return CourseLearnerState(
        schema_version=_as_int(_pick(raw, "schema_version", "schemaVersion", default=1), 1),
        user_id=str(_pick(raw, "user_id", "userId", default=user_id) or user_id),
        course_id=str(_pick(raw, "course_id", "courseId", "course", default=course_id) or course_id),
        goal_id=str(_pick(raw, "goal_id", "goalId", default="") or ""),
        progress=_as_float(_pick(raw, "progress", default=0.0), 0.0),
        knowledge=parse_knowledge(knowledge_raw),
        abilities=parse_abilities(_pick(raw, "abilities", default={})),
        misconceptions=parse_misconceptions(_pick(raw, "misconceptions", default=[])),
        behavior=parse_behavior(_pick(raw, "behavior", default={})),
        metadata=metadata,
        state_version=_as_int(
            _pick(raw, "state_version", "stateVersion", default=None), None
        )
        if _pick(raw, "state_version", "stateVersion", default=None) is not None
        else None,
        updated_at=_pick(raw, "updated_at", "updatedAt", default=None),
        freshness="fresh",
    )


def make_empty_course_state(user_id: str, course_id: str) -> CourseLearnerState:
    """合作伙伴不可用且无缓存时，返回显式的空状态（freshness=missing）。"""
    state = CourseLearnerState(user_id=user_id, course_id=course_id)
    state.freshness = "missing"
    return state


def make_mock_course_state(raw: Dict[str, Any], user_id: str, course_id: str) -> CourseLearnerState:
    """把 mock_provider 的字典转成 CourseLearnerState（freshness=mock）。"""
    state = parse_course_state(raw, user_id=user_id, course_id=course_id)
    state.freshness = "mock"
    return state
