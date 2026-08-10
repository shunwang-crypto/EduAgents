"""Mastery Policy：掌握度 → 深度/难度/脚手架/基础动作。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_LOW_TARGET_MASTERY, REASON_TARGET_MASTERED

MASTERED_THRESHOLD = 0.7


def mastery_policy(mastery: float, reason_codes: List[str]) -> Dict[str, object]:
    """掌握度 → 深度/难度/基础动作。"""
    if mastery < 0.3:
        reason_codes.append(REASON_LOW_TARGET_MASTERY)
        return {
            "depth": "basic",
            "difficulty": "easy",
            "scaffold_level": "high",
            "pedagogical_actions": ["EXPLAIN", "WORKED_EXAMPLE"],
            "review_or_new": "new",
        }
    if mastery < MASTERED_THRESHOLD:
        return {
            "depth": "medium",
            "difficulty": "medium",
            "scaffold_level": "medium",
            "pedagogical_actions": ["EXPLAIN", "WORKED_EXAMPLE", "CHECK_UNDERSTANDING"],
            "review_or_new": "new",
        }
    reason_codes.append(REASON_TARGET_MASTERED)
    return {
        "depth": "concise",
        "difficulty": "hard",
        "scaffold_level": "low",
        "pedagogical_actions": ["SUMMARIZE", "DEEPEN", "SOCRATIC_QUESTION"],
        "review_or_new": "review",
    }
