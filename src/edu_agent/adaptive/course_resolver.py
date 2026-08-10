"""CourseResolver：学习主题 → 稳定 course_id。

- 内置课程（JAVA-OOP / TRANSFORMER 等）优先匹配。
- 自定义课程：CUSTOM-{slug-or-hash}（稳定，不随机变化）。
- 业务层禁止到处使用默认 course_id，统一通过 LearningContext + resolve_course。
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

# 内置课程主题关键词 → 稳定 course_id
_BUILTIN_COURSES = {
    "java": "JAVA-OOP",
    "java oop": "JAVA-OOP",
    "面向对象": "JAVA-OOP",
    "oop": "JAVA-OOP",
    "transformer": "TRANSFORMER",
    "注意力": "TRANSFORMER",
    "attention": "TRANSFORMER",
}


def slugify(topic: str) -> str:
    """生成可读 slug（保留 ascii 字母数字，其余转 '-'）。"""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug


def resolve_course_id(topic: str, existing_course_ids: Optional[list] = None) -> str:
    """根据学习主题解析稳定 course_id。

    1. 内置课程关键词命中 → 内置 ID。
    2. 已有自定义课程中 slug 匹配 → 复用。
    3. 否则新建 CUSTOM-{slug or hash8}（稳定）。
    """
    topic = (topic or "").strip()
    if not topic:
        return "CUSTOM-unknown"
    lower = topic.lower()
    for keyword, course_id in _BUILTIN_COURSES.items():
        if keyword in lower:
            return course_id

    slug = slugify(topic)
    if slug:
        candidate = f"CUSTOM-{slug}"
        if len(candidate) > 48:
            candidate = candidate[:48]
    else:
        # 全中文等无 ascii 的主题 → hash 稳定后缀
        candidate = f"CUSTOM-{hashlib.sha1(topic.encode('utf-8')).hexdigest()[:8]}"

    if existing_course_ids:
        # 已有自定义课程按 slug 前缀复用（避免重复建课）
        prefix = candidate.rsplit("-", 1)[0]
        for cid in existing_course_ids:
            if cid.startswith(prefix) or cid == candidate:
                return cid
    return candidate


def resolve_goal_id(user_id: str, course_id: str) -> str:
    """稳定且 user scoped 的 goal_id（同用户同课程同目标）。"""
    return f"GOAL-{user_id}-{course_id}"[:64]
