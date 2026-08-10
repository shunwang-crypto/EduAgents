"""Preference Updater：完整生命周期。

candidate → active → weakening → inactive（可 reactivate → candidate/active）。
规则：
- pos 证据：score/confidence 上升（alpha = weight*0.3，封顶 0.15）。
- neg 证据：score/confidence 下降；active 连续 neg → weakening → inactive。
- USER_EXPLICIT：直接设置 score/direction，confidence=0.9（用户声明最高优先级）。
- 状态阈值：confidence≥0.5 → active；连续 neg 且 confidence<0.3 → weakening；
  confidence<0.15 → inactive。
- scope：course_id='' → global；否则 course。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

_DEFAULT_SCORE = 0.5
_DEFAULT_CONFIDENCE = 0.1
_ACTIVE_CONFIDENCE = 0.5
_WEAKENING_CONFIDENCE = 0.35
_INACTIVE_CONFIDENCE = 0.15
_ALPHA_CAP = 0.15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_status(status: str, direction: str, confidence: float) -> str:
    """偏好状态机（candidate/active/weakening/inactive）。"""
    if direction == "pos":
        if status == "inactive":
            return "candidate"  # reactivate 起点
        if confidence >= _ACTIVE_CONFIDENCE:
            return "active"
        if status == "active":
            return "active"
        return "candidate"
    # neg
    if confidence < _INACTIVE_CONFIDENCE:
        return "inactive"
    if status == "active" and confidence < _WEAKENING_CONFIDENCE:
        return "weakening"
    if status == "weakening" and confidence < _WEAKENING_CONFIDENCE:
        return "weakening"
    return status or "candidate"


def apply_preference_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条偏好证据。"""
    key = evidence.entity_key
    if not key:
        return {"operation": "NONE", "reason": "empty key", "scope": "global"}
    user_id = evidence.user_id
    course_id = evidence.course_id or ""
    scope = "global" if not course_id else "course"
    now = _now_iso()

    existing = repo.get_preference(user_id, key, course_id)
    before: Dict[str, Any] = {
        "score": float(existing["score"]) if existing else None,
        "confidence": float(existing["confidence"]) if existing else None,
        "status": existing.get("status", "candidate") if existing else "candidate",
        "evidence_count": int((existing or {}).get("evidence_count", 0)),
    }
    score = before["score"] if before["score"] is not None else _DEFAULT_SCORE
    confidence = before["confidence"] if before["confidence"] is not None else _DEFAULT_CONFIDENCE
    evidence_count = before["evidence_count"] + 1
    status = before["status"]

    op = "UPDATE" if existing else "CREATE"
    alpha = min(evidence.weight * 0.3, _ALPHA_CAP)

    if evidence.event_type == "USER_EXPLICIT_PREFERENCE":
        payload = evidence.payload or {}
        if "score" in payload:
            score = max(0.0, min(1.0, float(payload["score"])))
        else:
            score = score + (0.3 if evidence.direction == "pos" else -0.3)
        score = max(0.0, min(1.0, score))
        confidence = 0.9
        op = "USER_EXPLICIT_UPDATE"
        status = "active"
    elif evidence.direction == "pos":
        score = score + alpha * (1.0 - score)
        confidence = confidence + alpha * (1.0 - confidence)
        status = _next_status(status, "pos", confidence)
    elif evidence.direction == "neg":
        score = score - alpha * score
        confidence = confidence - alpha * confidence
        status = _next_status(status, "neg", confidence)
        if status == "inactive":
            op = "DEACTIVATE"
        elif status == "weakening":
            op = "WEAKEN"
        elif status == "candidate" and existing and before["status"] == "active":
            op = "WEAKEN"

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
        "before": before,
        "after": {"score": round(score, 4), "confidence": round(confidence, 4), "status": status, "evidence_count": evidence_count},
        "reason": f"{evidence.event_type} ({evidence.direction})",
        "scope": scope,
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
    payload: Dict[str, Any] = {"preference_key": preference_key}
    if score is not None:
        payload["score"] = score
    else:
        payload["direction"] = direction
    event = LearningEvent(
        event_id=f"EV-USER-{now}",
        event_type="USER_EXPLICIT_PREFERENCE",
        user_id=user_id,
        course_id=course_id,
        timestamp=now,
        source="USER_EXPLICIT",
        evidence_strength="strong",
        payload=payload,
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
