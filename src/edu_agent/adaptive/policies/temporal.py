"""Temporal Policy：时间衰减 → review_or_new。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_HIGH_REVIEW_RISK


def temporal_policy(temporal: object, reason_codes: List[str]) -> Dict[str, object]:
    """复习风险高/中 → 复习优先，先总结 + 理解检查。"""
    state = temporal
    if getattr(state, "review_risk", "low") in ("high", "medium"):
        reason_codes.append(REASON_HIGH_REVIEW_RISK)
        return {
            "review_or_new": "review",
            "pedagogical_actions": ["SUMMARIZE", "CHECK_UNDERSTANDING"],
        }
    return {}
