"""Knowledge State Updater。

保守原则：
- 曝光证据（neutral）：只更新 last_evidence_at / evidence_count，绝不改 mastery。
- SELF_REPORTED_UNDERSTANDING（pos）：只微升 confidence，mastery 不动。
- SELF_REPORTED_CONFUSION（neg）：只微降 confidence / 提高「需要辅导」信号，mastery 不动。
- 大幅 mastery 变更必须等强证据（未来 ASSESSMENT_RESULT），当前不实现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

_MASTERY_THRESHOLDS = (0.3, 0.7)
_CONFIDENCE_DELTA = 0.05  # 弱证据置信度微调幅度


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_for(mastery: float) -> str:
    if mastery >= _MASTERY_THRESHOLDS[1]:
        return "mastered"
    if mastery >= _MASTERY_THRESHOLDS[0]:
        return "learning"
    return "weak"


def apply_knowledge_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条 knowledge 证据，返回变更描述（供 change log）。"""
    kc_id = evidence.entity_key
    if not kc_id:
        return {"operation": "NONE", "reason": "empty kc"}
    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()

    existing = repo.get_kc(user_id, course_id, kc_id)
    if existing is None:
        # 首次观察：只建最小状态，不编造掌握度
        repo.upsert_kc(
            {
                "user_id": user_id,
                "course_id": course_id,
                "kc_id": kc_id,
                "kc_name": evidence.payload.get("kc_name") or kc_id,
                "mastery": 0.0,
                "confidence": None,
                "status": "unknown",
                "trend": None,
                "evidence_count": 1,
                "first_evidence_at": now,
                "last_evidence_at": now,
                "is_estimated": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {"operation": "CREATE", "entity": f"kc:{kc_id}", "reason": "first observation"}

    mastery = float(existing.get("mastery", 0.0))
    confidence = existing.get("confidence")
    evidence_count = int(existing.get("evidence_count", 0)) + 1
    status = existing.get("status", "unknown")
    trend = existing.get("trend")

    op = "UPDATE"
    if evidence.direction == "neutral":
        # 曝光：只更新时间与计数
        pass
    elif evidence.direction == "pos":
        # 弱理解证据：微升 confidence（若已知），mastery 不变
        if confidence is not None:
            confidence = min(1.0, confidence + _CONFIDENCE_DELTA)
            if confidence >= 0.5 and status == "unknown":
                status = _status_for(mastery)
    elif evidence.direction == "neg":
        # 困惑证据：微降 confidence（若已知），mastery 不变
        if confidence is not None:
            confidence = max(0.0, confidence - _CONFIDENCE_DELTA)
    else:
        op = "NONE"

    # 趋势：根据最近方向（简单规则）
    if evidence.direction == "pos":
        trend = "improving"
    elif evidence.direction == "neg":
        trend = "declining" if trend != "declining" else trend

    repo.upsert_kc(
        {
            "user_id": user_id,
            "course_id": course_id,
            "kc_id": kc_id,
            "kc_name": existing.get("kc_name") or kc_id,
            "mastery": mastery,
            "confidence": confidence,
            "status": status,
            "trend": trend,
            "evidence_count": evidence_count,
            "first_evidence_at": existing.get("first_evidence_at") or now,
            "last_evidence_at": now,
            "is_estimated": existing.get("is_estimated", 0),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
    )
    return {
        "operation": op,
        "entity": f"kc:{kc_id}",
        "reason": f"{evidence.event_type} ({evidence.direction})",
    }
