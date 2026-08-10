"""Ability Policy：理解能力低 → 简化 + 分步骤。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_LOW_UNDERSTANDING_ABILITY


def ability_policy(
    abilities: Dict[str, float],
    reason_codes: List[str],
) -> Dict[str, object]:
    """understanding 能力 < 0.3 → 降低抽象 + 分步骤。"""
    understanding = abilities.get("understanding", 0.5)
    if understanding < 0.3:
        reason_codes.append(REASON_LOW_UNDERSTANDING_ABILITY)
        return {
            "pedagogical_actions": ["DECOMPOSE", "SIMPLIFY", "EXPLAIN"],
            "depth": "basic",
        }
    return {}
