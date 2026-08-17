"""自适应系统的集中阈值配置。

UNKNOWN != 0：
- mastery is None 表示"未评估"，绝不转换为 0.0。
- 阈值只在 mastery 已知（非 None）时参与判定。
"""

from __future__ import annotations

# 掌握度阈值（与 LearnerModelService 既有用法保持一致，集中定义）
MASTERED_THRESHOLD: float = 0.70     # >= 视为 mastered
WEAK_THRESHOLD: float = 0.40        # < 视为 weak；[WEAK, MASTERED) 视为 learning

# 连续表现用于难度调整
CONSECUTIVE_SUCCESS_BUMP: int = 2    # 连续答对达到该次数 → 提升难度
CONSECUTIVE_ERROR_DROP: int = 2      # 连续答错达到该次数 → 降低难度


def classify_status(mastery: float | None) -> str:
    """统一 KC 状态分类（unknown / weak / learning / mastered）。

    仅接收标量 mastery；UNKNOWN 由调用方在 mastery is None 时直接判定。
    """
    if mastery is None:
        return "unknown"
    if mastery < WEAK_THRESHOLD:
        return "weak"
    if mastery < MASTERED_THRESHOLD:
        return "learning"
    return "mastered"
