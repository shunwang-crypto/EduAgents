"""CourseResolver：学习主题 → 稳定 course_id。

- 内置课程关键词（java/transformer 等）→ 内置 ID。
- 自定义课程：`CUSTOM-{slug}-{hash8}`（slug 可读 + hash 防 prefix collision）。
  相同 normalized topic → 相同 course_id；相似但不同的主题 → 不同 course_id（不误合并）。
- 业务层禁止到处使用默认 course_id，统一通过 LearningContext。
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, Optional

_BUILTIN_COURSES: Dict[str, str] = {
    "java oop": "JAVA-OOP",
    "java": "JAVA-OOP",
    "面向对象": "JAVA-OOP",
    "oop": "JAVA-OOP",
    "transformer": "TRANSFORMER",
    "注意力": "TRANSFORMER",
    "attention": "TRANSFORMER",
}

# ASCII 关键词按 token/word boundary 匹配，避免 "javascript" 误命中 "java"；
# 中文关键词按明确短语匹配。
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _match_builtin(topic: str) -> Optional[str]:
    lower = (topic or "").strip().lower()
    if not lower:
        return None
    tokens = set(_TOKEN_RE.findall(lower))
    for keyword, course_id in _BUILTIN_COURSES.items():
        kw_tokens = _TOKEN_RE.findall(keyword)
        if not kw_tokens:
            # 中文短语：直接子串匹配
            if keyword in lower:
                return course_id
            continue
        if len(kw_tokens) == 1:
            if kw_tokens[0] in tokens:
                return course_id
        else:
            # 多 token 短语：按空格拼接后在 lower 中连续出现
            if " ".join(kw_tokens) in lower:
                return course_id
    return None


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug


def _stable_suffix(topic: str) -> str:
    return hashlib.sha1(topic.strip().encode("utf-8")).hexdigest()[:8]


def resolve_course_id(topic: str, existing_course_ids: Optional[list] = None) -> str:
    """根据学习主题解析稳定 course_id。

    ASCII 关键词使用 token/word boundary 匹配，避免 "javascript" 误命中 "java"；
    中文关键词按明确短语匹配。相同 normalized topic → 相同 course_id（Fresh Baseline 无旧格式兼容）。
    """
    topic = (topic or "").strip()
    if not topic:
        return "CUSTOM-unknown"
    builtin = _match_builtin(topic)
    if builtin is not None:
        return builtin

    slug = slugify(topic)
    suffix = _stable_suffix(topic)
    candidate = f"CUSTOM-{slug[:24]}-{suffix}" if slug else f"CUSTOM-{suffix}"

    # 复用已有同主题课程（normalized slug + hash 完全一致才复用，避免误合并）
    for cid in existing_course_ids or []:
        if cid == candidate:
            return cid
    return candidate


def resolve_goal_id(user_id: str, course_id: str) -> str:
    """稳定且 user scoped 的 goal_id（同用户同课程同目标）。"""
    return f"GOAL-{user_id}-{course_id}"[:64]
