"""Preference Updater：偏好可升可降、可失效、可恢复。

生命周期：candidate → active → weakening → inactive（可 reactivate）。
规则：
- pos 证据：score 上升，confidence 上升（alpha = weight*0.3，封顶）。
- neg 证据：score 下降，confidence 下降（同 alpha）。
- USER_EXPLICIT：直接按 payload 设置 score/direction，confidence=0.9（用户声明优先）。
- 状态转换：confidence>=0.5 → active；score 连续 neg 后 confidence<0.15 → inactive；
  inactive 后再次 pos → reactivate。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

_DEFAULT_SCORE = 0.5
_DEFAULT_CONFIDENCE = 0.1
_ACTIVE_CONFIDENCE = 0.5
_INACTIVE_CONFIDENCE = 0.15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_preference_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条偏好证据（course_id 为空表示跨课程长期偏好）。"""
    key = evidence.entity_key
    if not key:
        return {"operation": "NONE", "reason": "empty key"}
    user_id = evidence.user_id
    course_id = evidence.course_id or ""
    now = _now_iso()

    existing = repo.get_preference(user_id, key, course_id)
    score = float(existing["score"]) if existing else _DEFAULT_SCORE
    confidence = float(existing["confidence"]) if existing else _DEFAULT_CONFIDENCE
    evidence_count = int((existing or {}).get("evidence_count", 0)) + 1
    status = existing.get("status", "candidate") if existing else "candidate"

    alpha = min(evidence.weight * 0.3, 0.15)
    op = "UPDATE" if existing else "CREATE"

    if evidence.event_type == "USER_EXPLICIT_PREFERENCE":
        # 用户明确声明：强证据，直接设置
        payload = evidence.payload or {}
        if "score" in payload:
            score = max(0.0, min(1.0, float(payload["score"])))
        else:
            score = score + (0.3 if evidence.direction == "pos" else -0.3)
        score = max(0.0, min(1.0, score))
        confidence = 0.9
        op = "USER_EXPLICIT_UPDATE"
    elif evidence.direction == "pos":
        score = score + alpha * (1.0 - score)
        confidence = confidence + alpha * (1.0 - confidence)
    elif evidence.direction == "neg":
        score = score - alpha * score
        confidence = confidence - alpha * confidence

    # 状态机
    if confidence >= _ACTIVE_CONFIDENCE:
        status = "active"
    elif confidence < _INACTIVE_CONFIDENCE:
        status = "inactive" if evidence.direction == "neg" else status
    else:
        if status not in ("active",):
            status = "candidate" if not existing else status
    if status == "inactive" and evidence.direction == "pos":
        status = "candidate"  # reactivate 起点

    repo.upsert_preference(
        {
            "user_id": user_id,
            "course_id": course_id,
            "preference_key": key,
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "evidence_count": evidence_count,
            "status": status,
            "first_observed_at": (existing or {}).get("first_observed_at") or now,
            "last_observed_at": now,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
    )
    return {
        "operation": op,
        "entity": f"preference:{key}",
        "reason": f"{evidence.event_type} ({evidence.direction})",
    }


def set_preference_direct(
    repo: LearnerRepository,
    user_id: str,
    preference_key: str,
    score: Optional[float] = None,
    direction: str = "pos",
    course_id: str = "",
) -> Dict[str, Any]:
    """用户/前端直接设置偏好（USER_EXPLICIT 级）。"""
    from edu_agent.learner_model.evidence.schemas import LearningEvent, StructuredEvidence

    now = _now_iso()
    event = LearningEvent(
        event_id=f"EV-USER-{now}",
        event_type="USER_EXPLICIT_PREFERENCE",
        user_id=user_id,
        course_id=course_id,
        timestamp=now,
        source="USER_EXPLICIT",
        evidence_strength="strong",
        payload={"preference_key": preference_key, "score": score} if score is not None else {"preference_key": preference_key, "direction": direction},
    )
    evidence = StructuredEvidence.from_event(
        event,
        entity_type="preference",
        entity_key=preference_key,
        direction=direction,
        meaningful=True,
        extra_payload=event.payload,
    )
    return apply_preference_evidence(repo, evidence)
