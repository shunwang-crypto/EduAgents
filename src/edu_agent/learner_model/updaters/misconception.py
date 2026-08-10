"""Misconception Updater：完整生命周期。

candidate → active → resolving → resolved（可 reactivate → active）。
- pos 证据（出现错误理解）：CREATE candidate / REINFORCE（confidence↑ severity↑ occurrence++）
- neg 证据（后续表现正确）：WEAKEN（confidence↓）→ resolving → resolved
- resolved 后再次 pos：REACTIVATE → active
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

_ACTIVE_CONFIDENCE = 0.5
_RESOLVING_CONFIDENCE = 0.4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_matching(
    repo: LearnerRepository, user_id: str, course_id: str, kc_id: str
) -> Optional[dict]:
    for m in repo.list_misconceptions(user_id, course_id):
        if m.get("kc_id") == kc_id and m.get("status") in ("candidate", "active", "resolving"):
            return m
    # resolved 也返回，供 reactivate
    for m in repo.list_misconceptions(user_id, course_id):
        if m.get("kc_id") == kc_id:
            return m
    return None


def apply_misconception_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条误解证据（entity_key=kc_id）。"""
    kc_id = evidence.entity_key
    if not kc_id:
        return {"operation": "NONE", "reason": "empty kc"}
    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()

    existing = _find_matching(repo, user_id, course_id, kc_id)

    if existing is None:
        if evidence.direction != "pos":
            return {"operation": "NONE", "reason": "no misconception and no positive signal"}
        # CREATE candidate
        m_id = f"MIS-{uuid.uuid4().hex[:12]}"
        repo.upsert_misconception(
            {
                "misconception_id": m_id,
                "user_id": user_id,
                "course_id": course_id,
                "kc_id": kc_id,
                "type": "conceptual_confusion",
                "description": (evidence.payload or {}).get("description_hint") or f"{kc_id} 相关概念混淆",
                "severity": 0.3,
                "confidence": max(0.2, min(0.6, evidence.weight + 0.1)),
                "occurrence_count": 1,
                "status": "candidate",
                "first_seen_at": now,
                "last_seen_at": now,
                "resolved_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {"operation": "CREATE", "entity": f"misconception:{kc_id}", "reason": evidence.event_type}

    m_id = existing["misconception_id"]
    confidence = float(existing.get("confidence", 0.3))
    severity = float(existing.get("severity", 0.5))
    occurrence = int(existing.get("occurrence_count", 1))
    status = existing.get("status", "candidate")
    resolved_at = existing.get("resolved_at")

    if evidence.direction == "pos":
        # REINFORCE
        occurrence += 1
        confidence = min(1.0, confidence + evidence.weight * 0.4)
        severity = min(1.0, severity + evidence.weight * 0.2)
        if status == "resolved":
            status = "active"  # REACTIVATE
            resolved_at = None
            op = "REACTIVATE"
        elif confidence >= _ACTIVE_CONFIDENCE:
            status = "active"
            op = "REINFORCE"
        else:
            status = "active" if status == "resolving" else "candidate"
            op = "REINFORCE"
    else:
        # WEAKEN（理解转正确）
        confidence = max(0.0, confidence - evidence.weight * 0.35)
        if confidence <= _RESOLVING_CONFIDENCE and status in ("active", "candidate"):
            status = "resolving"
            op = "WEAKEN"
        elif status == "resolving" and confidence <= 0.1:
            status = "resolved"
            resolved_at = now
            op = "RESOLVE"
        else:
            op = "WEAKEN"

    repo.upsert_misconception(
        {
            "misconception_id": m_id,
            "user_id": user_id,
            "course_id": course_id,
            "kc_id": kc_id,
            "type": existing.get("type", "conceptual_confusion"),
            "description": existing.get("description") or f"{kc_id} 相关概念混淆",
            "severity": round(severity, 4),
            "confidence": round(confidence, 4),
            "occurrence_count": occurrence,
            "status": status,
            "first_seen_at": existing.get("first_seen_at") or now,
            "last_seen_at": now,
            "resolved_at": resolved_at,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
    )
    return {"operation": op, "entity": f"misconception:{kc_id}", "reason": evidence.event_type}
