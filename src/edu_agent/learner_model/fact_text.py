"""Fact 人类可读化（共享 helper）。

PlanContext / ChatContext 共用：
- fact_value_json 必须先 json.loads，不能把带 JSON 引号的原始字符串塞进 LLM Prompt；
- 内部键格式（skill:python / no_python / background:{course}）不进入 Prompt，
  统一转成人类可读短语。
"""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_fact_value_json(raw: Optional[str]) -> Any:
    """解析 fact_value_json；损坏或非 JSON 原样返回。"""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def humanize_profile_fact(fact_key: str, fact_value_json: Optional[str]) -> str:
    """fact_key + fact_value_json → 人类可读短语。

    例：
      skill:python  "Python"        → "已掌握 Python"
      no_python     {"level":"none"} → "无 Python 基础"
      background:PY "数据分析"       → "PY 课程背景：数据分析"
    """
    key = fact_key or ""
    value = parse_fact_value_json(fact_value_json)
    text = value if isinstance(value, str) else ""

    if key.startswith("skill:"):
        return f"已掌握 {key[len('skill:'):]}"
    if key.startswith("no_"):
        return f"无 {key[len('no_'):]} 基础"
    if key.startswith("background:"):
        course = key[len("background:"):]
        return f"{course} 课程背景：{text}" if text else f"{course} 课程背景"
    # 通用兜底：字符串直接用；dict 只取人类字段
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        note = value.get("note") or value.get("level") or ""
        return str(note) if note else key
    return key
