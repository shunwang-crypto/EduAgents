"""Misconception Policy：活跃误解 → 针对性动作（反例/概念对比）。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_ACTIVE_MISCONCEPTION


def misconception_policy(
    misconceptions: List[dict],
    reason_codes: List[str],
) -> Dict[str, object]:
    """活跃且严重度 ≥ 0.5 的误解 → CONCEPT_COMPARISON + COUNTEREXAMPLE。"""
    active = [
        m for m in misconceptions
        if m.get("status", "active") == "active" and m.get("severity", 0) >= 0.5
    ]
    if active:
        reason_codes.append(REASON_ACTIVE_MISCONCEPTION)
        return {
            "pedagogical_actions": ["CONCEPT_COMPARISON", "COUNTEREXAMPLE"] + ["EXPLAIN"],
            "content_order": ["misconception_clarify"],
        }
    return {}
