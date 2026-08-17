"""自适应学习系统的统一 Reason Code 定义。

所有 Planner / Policy / LearningMap 产生的"为什么推荐某个 KC / 某个动作"
都必须使用这里的枚举值，避免散落字符串。
"""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    """可解释推荐原因码。"""

    # --- 状态类 ---
    UNKNOWN_STATE = "UNKNOWN_STATE"              # KC 尚未评估（mastery=None）
    LOW_MASTERY = "LOW_MASTERY"                  # 掌握度低于阈值
    MISCONCEPTION_DETECTED = "MISCONCEPTION_DETECTED"  # 检测到误区

    # --- 前置依赖类 ---
    PREREQUISITE_FOR_GOAL = "PREREQUISITE_FOR_GOAL"      # 是达成目标的关键前置
    PREREQUISITE_NOT_MET = "PREREQUISITE_NOT_MET"        # 前置未满足 → 锁定
    PREREQUISITE_SATISFIED = "PREREQUISITE_SATISFIED"    # 前置已满足 → 解锁

    # --- 近期表现类 ---
    RECENT_ERROR = "RECENT_ERROR"                # 最近答错
    RECENT_SUCCESS = "RECENT_SUCCESS"            # 最近答对

    # --- 目标 / 计划类 ---
    GOAL_RELEVANT = "GOAL_RELEVANT"              # 与目标相关
    NEXT_IN_PLAN = "NEXT_IN_PLAN"                # 计划中的下一步

    # --- 掌握度 / 复习类 ---
    MASTERY_THRESHOLD_REACHED = "MASTERY_THRESHOLD_REACHED"  # 达到掌握阈值
    REVIEW_REQUIRED = "REVIEW_REQUIRED"          # 需要复习


# 便于序列化 / 校验
REASON_CODE_VALUES: tuple[str, ...] = tuple(m.value for m in ReasonCode)
