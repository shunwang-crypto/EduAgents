"""Confidence Policy：置信度低 → 保守教学（不武断 mastered/weak）。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_LOW_MASTERY_CONFIDENCE

CONFIDENCE_THRESHOLD = 0.5


def confidence_policy(confidence: float, reason_codes: List[str]) -> Dict[str, object]:
    """置信度低（或未知→0.0）→ 保守：多理解检查，不武断判定。"""
    if confidence < CONFIDENCE_THRESHOLD:
        reason_codes.append(REASON_LOW_MASTERY_CONFIDENCE)
        return {
            "pedagogical_actions": ["EXPLAIN", "CHECK_UNDERSTANDING"],
            "scaffold_level": "medium",
        }
    return {}
