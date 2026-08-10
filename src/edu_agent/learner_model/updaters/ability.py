"""Ability Updater：六维能力慢更新。

原则：
- 单次弱事件不能大幅改变能力分数。
- 使用小学习率 EMA：new_score = old + alpha*(target-old)，alpha = weight * 0.15（上限 0.1）。
- 只有 medium/strong 或聚合多次 weak 后 confidence 才会上升。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

ABILITY_TYPES = [
    "understanding", "application", "reasoning", "expression", "reflection", "transfer",
]

_LEARNING_RATE_CAP = 0.1
_CONFIDENCE_RATE = 0.05


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ability_target(evidence: StructuredEvidence) -> float:
    """根据事件方向得到能力目标分（弱证据只给中性目标，避免虚高）。"""
    if evidence.direction == "pos":
        return 0.75
    if evidence.direction == "neg":
        return 0.25
    return 0.5


def apply_ability_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条能力证据。弱证据（weight<0.15）只计数不调分。"""
    ability_type = evidence.entity_key
    if ability_type not in ABILITY_TYPES:
        return {"operation": "NONE", "reason": f"unknown ability {ability_type}"}

    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()
    existing = repo.get_ability(user_id, course_id, ability_type)
    score = float(existing["score"]) if existing else 0.0
    confidence = existing.get("confidence") if existing else None
    evidence_count = int(existing.get("evidence_count", 0)) + 1
    trend = existing.get("trend") if existing else None

    # 弱证据且无既有分数 → 不假装精确，保持低置信
    alpha = min(evidence.weight * 0.15, _LEARNING_RATE_CAP)
    if evidence.weight >= 0.15 or (existing and evidence.weight >= 0.1):
        target = _ability_target(evidence)
        score = score + alpha * (target - score)
        if confidence is None:
            confidence = _CONFIDENCE_RATE * evidence.weight * 10
        else:
            confidence = min(1.0, confidence + _CONFIDENCE_RATE * evidence.weight)
        if evidence.direction == "pos":
            trend = "improving"
        elif evidence.direction == "neg":
            trend = "declining"

    repo.upsert_ability(
        {
            "user_id": user_id,
            "course_id": course_id,
            "ability_type": ability_type,
            "score": round(score, 4),
            "confidence": confidence,
            "trend": trend,
            "evidence_count": evidence_count,
            "first_evidence_at": (existing or {}).get("first_evidence_at") or now,
            "last_evidence_at": now,
            "updated_at": now,
        }
    )
    return {
        "operation": "UPDATE" if existing else "CREATE",
        "entity": f"ability:{ability_type}",
        "reason": f"{evidence.event_type} (weight={evidence.weight:.2f})",
    }
