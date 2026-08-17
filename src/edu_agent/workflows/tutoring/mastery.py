"""Deterministic mastery 更新：Evidence → delta。

禁止让 LLM 直接返回 mastery 写库。由这里根据结构化 Evidence 计算 delta，
再由 LearnerModelService 的 deterministic updater 应用。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# 集中配置：相对变化量（非绝对 mastery）
_GAIN_CORRECT: float = 0.12          # 答对基础增益
_GAIN_DIFFICULTY_W: float = 0.02     # 每级难度额外增益
_HINT_PENALTY: float = 0.04          # 每次 hint 降低增益
_LOSS_INCORRECT: float = 0.05        # 答错基础下降
_MISCONCEPTION_CONF_DROP: float = 0.15  # 误区导致 confidence 下降
_CONF_GAIN: float = 0.08
_CONF_LOSS: float = 0.06


def compute_mastery_delta(
    correctness: str,
    difficulty: int = 1,
    hint_level: int = 0,
    misconceptions: Optional[List[str]] = None,
) -> Tuple[float, float]:
    """返回 (mastery_delta, confidence_delta)。

    correctness: correct / partial / incorrect
    """
    misconceptions = misconceptions or []
    diff = max(1, min(3, int(difficulty)))
    hint_level = max(0, int(hint_level))

    if correctness == "correct":
        delta = _GAIN_CORRECT + _GAIN_DIFFICULTY_W * (diff - 1) - _HINT_PENALTY * hint_level
        delta = max(0.02, delta)  # 即使带 hint，正确仍有小增益
        conf = _CONF_GAIN
    elif correctness == "partial":
        delta = _GAIN_CORRECT * 0.4 - _HINT_PENALTY * hint_level * 0.5
        conf = _CONF_GAIN * 0.5
    else:  # incorrect
        delta = -_LOSS_INCORRECT
        conf = -_CONF_LOSS

    if misconceptions:
        # 明确误区：mastery 保持（不强行下降，避免误判），但 confidence 下降
        delta = min(delta, 0.0)
        conf -= _MISCONCEPTION_CONF_DROP

    return round(delta, 4), round(conf, 4)


def apply_delta(
    current_mastery: Optional[float],
    current_confidence: Optional[float],
    mastery_delta: float,
    confidence_delta: float,
) -> Tuple[Optional[float], Optional[float]]:
    """应用 delta 并裁剪到 [0,1]。UNKNOWN（None）首次正确 → 从 0.3 起算。"""
    if current_mastery is None:
        # 首次证据：从较低基线起步，绝不默认 0 也不默认 mastered
        new_mastery = 0.3 + max(0.0, mastery_delta)
    else:
        new_mastery = current_mastery + mastery_delta
    new_mastery = max(0.0, min(1.0, new_mastery))

    if current_confidence is None:
        new_conf = 0.2 + max(0.0, confidence_delta)
    else:
        new_conf = current_confidence + confidence_delta
    new_conf = max(0.0, min(1.0, new_conf))

    return round(new_mastery, 4), round(new_conf, 4)
