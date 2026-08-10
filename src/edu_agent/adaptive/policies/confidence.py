"""Confidence Policy：置信度低 → 保守教学（不武断 mastered/weak）。

confidence=None（UNKNOWN）→ 按低置信保守处理（LOW_MASTERY_CONFIDENCE）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.adaptive.reason_codes import REASON_LOW_MASTERY_CONFIDENCE

CONFIDENCE_THRESHOLD = 0.5


def confidence_policy(confidence: Optional[float], reason_codes: List[str]) -> Dict[str, object]:
    """置信度低（或未知）→ 保守：多理解检查，不武断判定。"""
    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        reason_codes.append(REASON_LOW_MASTERY_CONFIDENCE)
        return {
            "pedagogical_actions": ["EXPLAIN", "CHECK_UNDERSTANDING"],
            "scaffold_level": "medium",
        }
    return {}
