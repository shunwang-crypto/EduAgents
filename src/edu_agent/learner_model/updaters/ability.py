"""Ability Updater：六维能力慢更新。

原则：
- score=None 表示 UNKNOWN（无可靠证据），不是 0。
- 首次初始化：只有中等/强证据（weight≥0.2）才初始化合理估计值，
  不产生从 0 做 EMA 的假低分。
- 后续 EMA：小学习率（≤0.1），弱证据只计数不调分。
- confidence 低时（<0.4）Ability 不应显著影响教学策略（policy 侧处理）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository

ABILITY_TYPES = [
    "understanding", "application", "reasoning", "expression", "reflection", "transfer",
]

_LEARNING_RATE_CAP = 0.1
_CONFIDENCE_RATE = 0.08
# 首次初始化所需的证据强度
_INIT_MIN_WEIGHT = 0.2
_INIT_SCORES = {"pos": 0.6, "neg": 0.4, "neutral": 0.5}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_ability_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理一条能力证据。entity_key = ability_type。"""
    ability_type = evidence.entity_key
    if ability_type not in ABILITY_TYPES:
        return {"operation": "NONE", "reason": f"unknown ability {ability_type}", "scope": "course"}

    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()
    existing = repo.get_ability(user_id, course_id, ability_type)
    before: Dict[str, Any] = {
        "score": existing.get("score") if existing else None,
        "confidence": existing.get("confidence") if existing else None,
        "evidence_count": existing.get("evidence_count", 0) if existing else 0,
    }
    score = existing.get("score") if existing else None
    confidence = existing.get("confidence") if existing else None
    evidence_count = int((existing or {}).get("evidence_count", 0)) + 1
    trend = existing.get("trend") if existing else None

    op = "UPDATE" if existing else "CREATE"

    if score is None:
        # 首次初始化：需要中等/强证据（weight≥0.2），且要求语义分类器置信度
        classifier_conf = evidence.payload.get("classifier_confidence")
        has_classifier = (
            evidence.event_type == "CHECK_UNDERSTANDING_RESPONSE"
            and classifier_conf is not None
        )
        if evidence.weight >= _INIT_MIN_WEIGHT and (has_classifier or evidence.source == "USER_EXPLICIT"):
            score = _INIT_SCORES.get(evidence.direction, 0.5)
            confidence = min(0.5, 0.2 + evidence.weight)
            trend = "improving" if evidence.direction == "pos" else ("declining" if evidence.direction == "neg" else None)
        else:
            # 证据不足：只计数，不初始化假分数
            confidence = min(0.2, (confidence or 0.0) + _CONFIDENCE_RATE * evidence.weight)
            repo.upsert_ability(
                {
                    "user_id": user_id,
                    "course_id": course_id,
                    "ability_type": ability_type,
                    "score": None,
                    "confidence": confidence,
                    "trend": trend,
                    "evidence_count": evidence_count,
                    "first_evidence_at": (existing or {}).get("first_evidence_at") or now,
                    "last_evidence_at": now,
                    "updated_at": now,
                }
            )
            return {
                "operation": "NONE" if not existing else "UPDATE",
                "entity": f"ability:{ability_type}",
                "before": before,
                "after": {"score": None, "confidence": confidence, "evidence_count": evidence_count},
                "reason": f"{evidence.event_type} insufficient evidence",
                "scope": "course",
            }
    else:
        # EMA 慢更新
        alpha = min(evidence.weight * 0.15, _LEARNING_RATE_CAP)
        target = 0.75 if evidence.direction == "pos" else (0.25 if evidence.direction == "neg" else 0.5)
        if evidence.weight >= 0.1:
            score = round(score + alpha * (target - score), 4)
            confidence = min(1.0, (confidence or 0.0) + _CONFIDENCE_RATE * evidence.weight)
            if evidence.direction == "pos":
                trend = "improving"
            elif evidence.direction == "neg":
                trend = "declining"
        else:
            confidence = min(1.0, (confidence or 0.0) + _CONFIDENCE_RATE * evidence.weight * 0.5)

    repo.upsert_ability(
        {
            "user_id": user_id,
            "course_id": course_id,
            "ability_type": ability_type,
            "score": score,
            "confidence": confidence,
            "trend": trend,
            "evidence_count": evidence_count,
            "first_evidence_at": (existing or {}).get("first_evidence_at") or now,
            "last_evidence_at": now,
            "updated_at": now,
        }
    )
    return {
        "operation": op,
        "entity": f"ability:{ability_type}",
        "before": before,
        "after": {"score": score, "confidence": confidence, "evidence_count": evidence_count},
        "reason": f"{evidence.event_type} ({evidence.direction})",
        "scope": "course",
    }
