"""把内部学习偏好键转换为可直接注入提示词的人类可读文本。"""

from __future__ import annotations


_LABELS = {
    "concise_first": ("回答简洁直接", "不要过度简略"),
    "detailed_explanation": ("讲解充分详细", "避免冗长讲解"),
    "worked_example": ("结合完整示例", "避免过多示例"),
    "code_example": ("优先使用代码示例", "避免依赖代码示例"),
    "visual_explanation": ("使用图示说明", "避免依赖图示"),
    "theory_first": ("先讲理论原理", "避免纯理论优先"),
    "hands_on": ("优先动手实践", "不要以实践为主"),
    "step_by_step": ("分步骤讲解", "避免过度拆分步骤"),
    "analogy": ("使用类比帮助理解", "少用类比"),
}


def humanize_preference(preference_key: str, score: float) -> str:
    """score >= 0.6 表示偏好，score <= 0.4 表示明确不偏好。"""
    labels = _LABELS.get(preference_key)
    if not labels:
        return preference_key.replace("_", " ")
    return labels[0] if score >= 0.6 else labels[1]
