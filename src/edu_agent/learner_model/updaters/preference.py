"""Preference Updater（范围收缩版）：偏好可升降、可失效、可恢复。

生命周期：candidate → active → weakening → inactive（可 reactivate）。
- pos：score/confidence 上升；neg：下降。
- USER_EXPLICIT（source=USER_EXPLICIT）：直接设置 score/direction，confidence=0.9。
- scope：course_id='' → global；否则 course。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence_light import LightEvidence
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
    if direction == "pos":
        if status == "inactive":
            return "candidate"
        if confidence >= _ACTIVE_CONFIDENCE:
            return "active"
        return "active" if status == "active" else "candidate"
    if confidence < _INACTIVE_CONFIDENCE:
        return "inactive"
    if status in ("active",) and confidence < _WEAKENING_CONFIDENCE:
        return "weakening"
    return status or "candidate"


def apply_preference_evidence(
    repo: LearnerRepository, evidence: LightEvidence
) -> Dict[str, Any]:
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

    if evidence.source == "USER_EXPLICIT":
        payload = evidence.payload or {}
        if "score" in payload:
            score = max(0.0, min(1.0, float(payload["score"])))
        else:
            score = score + (0.3 if evidence.direction == "pos" else -0.3)
        score = max(0.0, min(1.0, score))
        confidence = 0.9
        status = "active"
        op = "USER_EXPLICIT_UPDATE"
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

    repo.upsert_preference(
        {"user_id": user_id, "course_id": course_id, "preference_key": key,
         "score": round(score, 4), "confidence": round(confidence, 4),
         "evidence_count": evidence_count, "status": status,
         "first_observed_at": (existing or {}).get("first_observed_at") or now,
         "last_observed_at": now, "created_at": (existing or {}).get("created_at") or now,
         "updated_at": now}
    )
    return {"operation": op, "entity": f"preference:{key}",
            "before": before,
            "after": {"score": round(score, 4), "confidence": round(confidence, 4),
                      "status": status, "evidence_count": evidence_count},
            "reason": f"{evidence.event_type} ({evidence.direction})", "scope": scope}


def set_preference_direct(
    repo: LearnerRepository, user_id: str, preference_key: str,
    score: Optional[float] = None, direction: str = "pos", course_id: str = "",
) -> Dict[str, Any]:
    """用户/前端直接设置偏好（USER_EXPLICIT 级）。"""
    payload: Dict[str, Any] = {"preference_key": preference_key}
    if score is not None:
        payload["score"] = score
    else:
        payload["direction"] = direction
    evidence = LightEvidence(
        user_id=user_id, course_id=course_id, entity_type="preference",
        entity_key=preference_key, direction=direction, event_type="USER_EXPLICIT_PREFERENCE",
        source="USER_EXPLICIT", payload=payload, weight=0.9,
    )
    return apply_preference_evidence(repo, evidence)
