"""Misconception Updater：同一 KC 可同时存在多个误解（按 misconception_key 区分）。

生命周期：candidate → active → resolving → resolved（可 reactivate → active）。
- pos 证据（出现错误理解）：CREATE candidate（携带 misconception_key）/ REINFORCE。
- neg 证据（后续表现正确）：WEAKEN → resolving → resolved。
- resolved 后再次 pos：REACTIVATE → active。
- 证据必须携带 misconception_key（缺失时用 kc_id 作为回退 key）。
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


def _key_of(evidence: StructuredEvidence) -> str:
    """误解标识：证据 payload.misconception_key，缺失回退 kc_id。"""
    return (evidence.payload or {}).get("misconception_key") or evidence.entity_key or ""


def apply_misconception_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条误解证据（entity_key=kc_id，payload.misconception_key 区分实例）。"""
    kc_id = evidence.entity_key
    if not kc_id:
        return {"operation": "NONE", "reason": "empty kc", "scope": "course"}
    key = _key_of(evidence)
    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()

    existing = repo.find_misconception(user_id, course_id, kc_id, key)

    if existing is None:
        if evidence.direction != "pos":
            return {"operation": "NONE", "reason": "no misconception and no positive signal", "scope": "course"}
        # CREATE candidate（支持同 KC 多个误解：misconception_key 区分）
        m_id = f"MIS-{uuid.uuid4().hex[:12]}"
        repo.upsert_misconception(
            {
                "misconception_id": m_id,
                "user_id": user_id,
                "course_id": course_id,
                "kc_id": kc_id,
                "misconception_key": key,
                "type": (evidence.payload or {}).get("type") or "conceptual_confusion",
                "description": (evidence.payload or {}).get("description_hint") or f"{kc_id}:{key} 相关概念混淆",
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
        return {
            "operation": "CREATE",
            "entity": f"misconception:{kc_id}:{key}",
            "before": None,
            "after": {"status": "candidate", "confidence": max(0.2, min(0.6, evidence.weight + 0.1))},
            "reason": evidence.event_type,
            "scope": "course",
        }

    m_id = existing["misconception_id"]
    before: Dict[str, Any] = {
        "status": existing.get("status"),
        "confidence": float(existing.get("confidence", 0.3)),
        "severity": float(existing.get("severity", 0.5)),
        "occurrence_count": int(existing.get("occurrence_count", 1)),
    }
    confidence = before["confidence"]
    severity = before["severity"]
    occurrence = before["occurrence_count"]
    status = before["status"]
    resolved_at = existing.get("resolved_at")

    if evidence.direction == "pos":
        occurrence += 1
        confidence = min(1.0, confidence + evidence.weight * 0.4)
        severity = min(1.0, severity + evidence.weight * 0.2)
        if status == "resolved":
            status = "active"
            resolved_at = None
            op = "REACTIVATE"
        elif confidence >= _ACTIVE_CONFIDENCE:
            status = "active"
            op = "REINFORCE"
        else:
            status = "active" if status == "resolving" else "candidate"
            op = "REINFORCE"
    else:
        confidence = max(0.0, confidence - evidence.weight * 0.35)
        if status in ("active", "candidate") and confidence <= _RESOLVING_CONFIDENCE:
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
            "misconception_key": key,
            "type": existing.get("type") or "conceptual_confusion",
            "description": existing.get("description") or f"{kc_id}:{key} 相关概念混淆",
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
    return {
        "operation": op,
        "entity": f"misconception:{kc_id}:{key}",
        "before": before,
        "after": {"status": status, "confidence": round(confidence, 4), "occurrence_count": occurrence},
        "reason": evidence.event_type,
        "scope": "course",
    }
