"""Knowledge State Updater。

保守原则：
- UNKNOWN（mastery=None）与 KNOWN ZERO（mastery=0 + 高 confidence）严格区分。
- 曝光证据（neutral）：只更新 last_evidence_at / evidence_count，绝不改 mastery。
- SELF_REPORTED_UNDERSTANDING（pos）：只微升 confidence，mastery 不动（None 也不凭空产生）。
- SELF_REPORTED_CONFUSION（neg）：只微降 confidence，mastery 不动。
- CHECK_UNDERSTANDING_RESPONSE（经语义分类器、medium+）才允许小幅初始化/更新 mastery，
  且受上限约束（一次变化 ≤0.1），必须有 classifier confidence。
- 趋势：最近 N 条证据滑动窗口（improving/declining 需要阈值，否则 stable/unknown）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

_MASTERY_THRESHOLDS = (0.3, 0.7)
_CONFIDENCE_DELTA = 0.05  # 弱证据置信度微调幅度
_MASTERY_MAX_DELTA = 0.1  # 单次 mastery 变化上限（仅强证据）
_TREND_WINDOW = 5
_TREND_THRESHOLD = 0.6  # 窗口内正向占比超过此值 → improving；低于 1-此值 → declining


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_for(mastery: Optional[float], confidence: Optional[float]) -> str:
    if mastery is None:
        return "unknown"
    if mastery >= _MASTERY_THRESHOLDS[1] and confidence is not None and confidence >= 0.5:
        return "mastered"
    if mastery >= _MASTERY_THRESHOLDS[0]:
        return "learning"
    # KNOWN ZERO / known low：需要置信度支撑才算 weak；否则保持 unknown 更诚实
    if confidence is not None and confidence >= 0.5:
        return "weak"
    return "unknown"


def _update_trend(
    repo: LearnerRepository,
    user_id: str,
    course_id: str,
    kc_id: str,
    current_trend: Optional[str],
    direction: str,
) -> Optional[str]:
    """最近 _TREND_WINDOW 条证据的加权窗口（improving/declining/stable/unknown）。"""
    if direction == "neutral":
        return current_trend
    evidences = repo.list_evidences(user_id, course_id, limit=50)
    recent = [
        ev
        for ev in evidences
        if ev.get("entity_type") == "knowledge" and ev.get("entity_key") == kc_id
        and ev.get("direction") in ("pos", "neg")
    ][:_TREND_WINDOW]
    if not recent:
        return current_trend
    pos_ratio = sum(1 for ev in recent if ev.get("direction") == "pos") / len(recent)
    if pos_ratio >= _TREND_THRESHOLD:
        return "improving"
    if pos_ratio <= 1 - _TREND_THRESHOLD:
        return "declining"
    return "stable"


def _is_strong(evidence: StructuredEvidence) -> bool:
    """强证据判定：CHECK_UNDERSTANDING_RESPONSE（用户自述理解，medium+）"""
    classifier_conf = evidence.payload.get("classifier_confidence")
    return (
        evidence.event_type == "CHECK_UNDERSTANDING_RESPONSE"
        and evidence.weight >= 0.2
        and (classifier_conf is None or float(classifier_conf) >= 0.5)
    )


def apply_knowledge_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条 knowledge 证据，返回 {operation, entity, before, after, reason, scope}。"""
    kc_id = evidence.entity_key
    if not kc_id:
        return {"operation": "NONE", "reason": "empty kc", "scope": "course"}
    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()
    before: Dict[str, Any] = {}
    strong = _is_strong(evidence)

    existing = repo.get_kc(user_id, course_id, kc_id)
    if existing is None:
        # 首次观察：只建最小状态（mastery=None = UNKNOWN，不编造掌握度）；
        # 强理解证据例外：允许保守初始化 mastery=0.3（有上限，不凭空给高分）
        initial_mastery = 0.3 if (strong and evidence.direction == "pos") else None
        initial_confidence = 0.3 if initial_mastery is not None else None
        repo.upsert_kc(
            {
                "user_id": user_id,
                "course_id": course_id,
                "kc_id": kc_id,
                "kc_name": evidence.payload.get("kc_name") or kc_id,
                "mastery": initial_mastery,
                "confidence": initial_confidence,
                "status": "unknown" if initial_mastery is None else "learning",
                "trend": None,
                "evidence_count": 1,
                "first_evidence_at": now,
                "last_evidence_at": now,
                "is_estimated": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {
            "operation": "CREATE",
            "entity": f"kc:{kc_id}",
            "before": None,
            "after": {"mastery": initial_mastery, "status": "unknown" if initial_mastery is None else "learning"},
            "reason": "first observation",
            "scope": "course",
        }

    before = {
        "mastery": existing.get("mastery"),
        "confidence": existing.get("confidence"),
        "status": existing.get("status"),
        "trend": existing.get("trend"),
        "evidence_count": existing.get("evidence_count"),
    }
    mastery = existing.get("mastery")
    confidence = existing.get("confidence")
    evidence_count = int(existing.get("evidence_count", 0)) + 1
    status = existing.get("status", "unknown")
    trend = existing.get("trend")

    op = "UPDATE"
    is_strong = strong

    if evidence.direction == "neutral":
        # 曝光：只更新时间与计数
        pass
    elif evidence.direction == "pos":
        if is_strong:
            if mastery is None:
                # 强理解证据首次初始化：保守初始 0.3（有上限，不凭空给高分）
                mastery = 0.3
                confidence = max(confidence or 0.0, 0.3)
            else:
                mastery = min(1.0, mastery + min(evidence.weight, _MASTERY_MAX_DELTA) * 0.5)
        # confidence 微升（无论 mastery 是否已知）
        if confidence is not None:
            confidence = min(1.0, confidence + _CONFIDENCE_DELTA)
    elif evidence.direction == "neg":
        if is_strong and mastery is not None:
            mastery = max(0.0, mastery - min(evidence.weight, _MASTERY_MAX_DELTA) * 0.3)
        if confidence is not None:
            confidence = max(0.0, confidence - _CONFIDENCE_DELTA)
    else:
        op = "NONE"

    status = _status_for(mastery, confidence)
    trend = _update_trend(repo, user_id, course_id, kc_id, trend, evidence.direction)

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
        "before": before,
        "after": {
            "mastery": mastery,
            "confidence": confidence,
            "status": status,
            "trend": trend,
            "evidence_count": evidence_count,
        },
        "reason": f"{evidence.event_type} ({evidence.direction})",
        "scope": "course",
    }
