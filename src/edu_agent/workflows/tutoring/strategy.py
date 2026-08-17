"""Deterministic Teaching Strategy：状态 → Teaching Action 映射。

第一版以确定性策略为主，不集中依赖 LLM。
阈值来自 adaptive.thresholds，避免散落硬编码。
"""

from __future__ import annotations

from typing import List, Optional

from edu_agent.adaptive.thresholds import (
    MASTERED_THRESHOLD,
    WEAK_THRESHOLD,
    classify_status,
)
from edu_agent.workflows.tutoring.schemas import TeachingAction


def decide_action(
    mastery: Optional[float],
    misconceptions: Optional[List[str]] = None,
    consecutive_errors: int = 0,
    consecutive_successes: int = 0,
    difficulty: int = 1,
) -> TeachingAction:
    """根据 learner 状态确定性选择 Teaching Action。"""
    misconceptions = misconceptions or []

    # 1. 未知 → 先评估
    if mastery is None:
        return TeachingAction.ASSESS

    # 2. 存在误区 → 探究 / 对比
    if misconceptions:
        return TeachingAction.PROBE if consecutive_errors == 0 else TeachingAction.COMPARE

    # 3. 连续错误 → 降难度，给提示 / 例子
    if consecutive_errors >= 2:
        return TeachingAction.HINT if difficulty > 1 else TeachingAction.EXAMPLE

    # 4. 连续正确 → 提升难度
    if consecutive_successes >= 2:
        if mastery >= MASTERED_THRESHOLD:
            return TeachingAction.APPLICATION
        return TeachingAction.CHALLENGE

    # 5. 按掌握度分区
    if mastery < WEAK_THRESHOLD:
        return TeachingAction.EXPLAIN
    if mastery < MASTERED_THRESHOLD:
        return TeachingAction.PRACTICE
    return TeachingAction.CHALLENGE


def tune_difficulty(
    base_difficulty: int,
    consecutive_errors: int = 0,
    consecutive_successes: int = 0,
) -> int:
    """根据连续表现调整难度（1..3）。"""
    d = base_difficulty
    if consecutive_errors >= 2:
        d -= 1
    if consecutive_successes >= 2:
        d += 1
    return max(1, min(3, d))
