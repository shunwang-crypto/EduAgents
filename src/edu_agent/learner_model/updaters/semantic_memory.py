"""Semantic Memory Updater：长期语义记忆（SQLite，未来可迁向量库）。

- CREATE / REINFORCE（同内容去重，importance 微升）/ DELETE。
- 用户明确删除 → 真正 DELETE。
- scope：course_id='' → global；否则 course。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(content: str) -> str:
    """轻量归一化指纹：小写、去空白/标点，减少近重复。"""
    text = re.sub(r"[\s，。、；：！？.,;:!?（）()\[\]【】\"']", "", content.lower())
    return text


def _find_memory(
    repo: LearnerRepository, user_id: str, content: str, course_id: str = ""
) -> Optional[dict]:
    """scope 内去重：course memory 只和同 course memory 去重，绝不强化 global。"""
    norm = _normalize(content)
    candidates = (
        repo.list_global_memories(user_id)
        if not course_id
        else repo.list_course_memories(user_id, course_id)
    )
    for m in candidates:
        if _normalize(m.get("content") or "") == norm:
            return m
    return None


def add_memory(
    repo: LearnerRepository,
    user_id: str,
    content: str,
    course_id: str = "",
    category: str = "experience",
    importance: float = 0.5,
    source: str = "USER_EXPLICIT",
) -> Dict[str, Any]:
    """新增或强化一条语义记忆（归一化去重 → REINFORCE）。"""
    now = _now_iso()
    scope = "global" if not course_id else "course"
    existing = _find_memory(repo, user_id, content, course_id)
    if existing:
        repo.upsert_memory(
            {
                **existing,
                "importance": min(1.0, float(existing.get("importance", 0.5)) + 0.1),
                "status": "active",
                "last_reinforced_at": now,
                "updated_at": now,
            }
        )
        return {
            "operation": "REINFORCE",
            "entity": f"memory:{existing['memory_id']}",
            "before": {"importance": existing.get("importance")},
            "after": {"importance": min(1.0, float(existing.get("importance", 0.5)) + 0.1)},
            "reason": "duplicate content",
            "scope": scope,
        }

    memory_id = f"MEM-{uuid.uuid4().hex[:12]}"
    repo.upsert_memory(
        {
            "memory_id": memory_id,
            "user_id": user_id,
            "course_id": course_id,
            "category": category,
            "content": content,
            "confidence": 0.9 if source == "USER_EXPLICIT" else 0.5,
            "importance": importance,
            "source": source,
            "status": "active",
            "first_seen_at": now,
            "last_reinforced_at": now,
            "updated_at": now,
            "expires_at": None,
        }
    )
    return {
        "operation": "CREATE",
        "entity": f"memory:{memory_id}",
        "before": None,
        "after": {"content": content[:60], "importance": importance},
        "reason": "add_memory",
        "scope": scope,
    }


def delete_memory_direct(
    repo: LearnerRepository, user_id: str, memory_id: str
) -> Dict[str, Any]:
    """用户明确删除：先读真实记录（判断存在性与 scope），再真正 DELETE。"""
    existing = repo.get_memory(user_id, memory_id)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}
    scope = "course" if existing.get("course_id") else "global"
    repo.delete_memory(user_id, memory_id)
    return {
        "operation": "DELETE",
        "entity": f"memory:{memory_id}",
        "before": {"content": (existing.get("content") or "")[:40], "scope": scope},
        "after": None,
        "reason": "user requested",
        "scope": scope,
    }
