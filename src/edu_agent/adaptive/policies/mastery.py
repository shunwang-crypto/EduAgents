"""Mastery Policy：掌握度 → 深度/难度/脚手架/基础动作。

三态严格区分：
- UNKNOWN（mastery=None）→ 中性首次教学，中等 scaffold，不武断说「你不会」，
  理由码 UNKNOWN_KNOWLEDGE_STATE（不是 LOW_TARGET_MASTERY）。
- KNOWN LOW（mastery<0.3 + 高 confidence）→ LOW_TARGET_MASTERY，basic/high scaffold。
- LOW BUT UNCERTAIN（mastery<0.3 + 低 confidence）→ 保守（LOW_MASTERY_CONFIDENCE 由 confidence 组件处理）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.adaptive.reason_codes import (
    REASON_LOW_TARGET_MASTERY,
    REASON_TARGET_MASTERED,
    REASON_UNKNOWN_KNOWLEDGE_STATE,
)

MASTERED_THRESHOLD = 0.7


def mastery_policy(mastery: Optional[float], reason_codes: List[str]) -> Dict[str, object]:
    """掌握度 → 深度/难度/基础动作。mastery=None 表示 UNKNOWN。"""
    if mastery is None:
        reason_codes.append(REASON_UNKNOWN_KNOWLEDGE_STATE)
        return {
            "depth": "medium",
            "difficulty": "medium",
            "scaffold_level": "medium",
            "pedagogical_actions": ["EXPLAIN", "CHECK_UNDERSTANDING"],
            "review_or_new": "new",
        }
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
