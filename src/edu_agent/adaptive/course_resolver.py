"""CourseResolver：学习主题 → 稳定 course_id。

- 内置课程关键词（java/transformer 等）→ 内置 ID。
- 自定义课程：`CUSTOM-{slug}-{hash8}`（slug 可读 + hash 防 prefix collision）。
  相同 normalized topic → 相同 course_id；相似但不同的主题 → 不同 course_id（不误合并）。
- 业务层禁止到处使用默认 course_id，统一通过 LearningContext。
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

_BUILTIN_COURSES = {
    "java oop": "JAVA-OOP",
    "java": "JAVA-OOP",
    "面向对象": "JAVA-OOP",
    "oop": "JAVA-OOP",
    "transformer": "TRANSFORMER",
    "注意力": "TRANSFORMER",
    "attention": "TRANSFORMER",
}


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug


def _stable_suffix(topic: str) -> str:
    return hashlib.sha1(topic.strip().encode("utf-8")).hexdigest()[:8]


def resolve_course_id(topic: str, existing_course_ids: Optional[list] = None) -> str:
    """根据学习主题解析稳定 course_id。"""
    topic = (topic or "").strip()
    if not topic:
        return "CUSTOM-unknown"
    lower = topic.lower()
    for keyword, course_id in _BUILTIN_COURSES.items():
        if keyword in lower:
            return course_id

    slug = slugify(topic)
    suffix = _stable_suffix(topic)
    candidate = f"CUSTOM-{slug[:24]}-{suffix}" if slug else f"CUSTOM-{suffix}"

    # 复用已有同主题课程（要求 normalized 前缀 + 相同 hash 才复用，避免误合并）
    prefix = f"CUSTOM-{slug[:24]}-" if slug else f"CUSTOM-"
    for cid in existing_course_ids or []:
        if cid == candidate:
            return cid
        # 旧格式兼容：同 slug 无 hash 后缀的旧课程
        if slug and cid == f"CUSTOM-{slug[:24]}":
            return cid
        if not slug and cid.startswith(prefix) and cid.endswith(suffix):
            return cid
    return candidate


def resolve_goal_id(user_id: str, course_id: str) -> str:
    """稳定且 user scoped 的 goal_id（同用户同课程同目标）。"""
    return f"GOAL-{user_id}-{course_id}"[:64]
