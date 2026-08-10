"""Preference Policy：偏好只决定交付形式，不改变教学需要。

原则：Pedagogical Need > Task Suitability > User Preference。
"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_PREFERENCE_WORKED_EXAMPLE


def preference_policy(
    preferences: dict,
    pedagogical_need: str,
    reason_codes: List[str],
) -> Dict[str, object]:
    """按教学需要 + 用户偏好选择交付模式与示例数。"""
    preferred_mode = preferences.get("preferred_mode", "")
    mode_effectiveness = preferences.get("mode_effectiveness", {}) or {}

    if pedagogical_need in ("EXPLAIN", "WORKED_EXAMPLE"):
        if preferred_mode in ("example_driven", "worked_example"):
            reason_codes.append(REASON_PREFERENCE_WORKED_EXAMPLE)
            return {"delivery_mode": "worked_example", "example_count": 2}
        if preferred_mode == "visual":
            return {"delivery_mode": "visual", "example_count": 1}
        if preferred_mode == "reading":
            return {"delivery_mode": "reading", "example_count": 1}

    # 用实测效果兜底：选效果最好的模式（无则保持默认 explanation）
    if mode_effectiveness:
        best_mode = max(
            mode_effectiveness.items(),
            key=lambda kv: kv[1].get("score", 0) if isinstance(kv[1], dict) else kv[1],
        )[0]
        return {"delivery_mode": best_mode, "example_count": 1}
    return {}
