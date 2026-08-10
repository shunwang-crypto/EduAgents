"""Ability Policy：理解能力低 → 简化 + 分步骤。

必须考虑 confidence：score 低但 confidence 低（证据不足）时，
不能武断按「低能力」处理。只有 confidence 足够（≥0.4）时能力才影响策略。
"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_LOW_UNDERSTANDING_ABILITY

_CONFIDENCE_GATE = 0.4


def ability_policy(
    abilities: Dict[str, dict],
    reason_codes: List[str],
) -> Dict[str, object]:
    """understanding 能力低且置信度足够 → 降低抽象 + 分步骤。"""
    understanding = abilities.get("understanding") or {}
    score = understanding.get("score")
    confidence = understanding.get("confidence")
    if score is None or confidence is None:
        return {}  # UNKNOWN：不按低能力处理
    if confidence < _CONFIDENCE_GATE:
        return {}  # 证据不足：保守，不武断
    if score < 0.3:
        reason_codes.append(REASON_LOW_UNDERSTANDING_ABILITY)
        return {
            "pedagogical_actions": ["DECOMPOSE", "SIMPLIFY", "EXPLAIN"],
            "depth": "basic",
        }
    return {}
