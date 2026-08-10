"""Semantic Memory Updater：长期语义记忆（SQLite，未来可迁向量库）。

- CREATE / REINFORCE（重复提及 confidence/importance 上升）/ DEACTIVATE / DELETE。
- 用户明确删除 → 真正 DELETE。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_memory(
    repo: LearnerRepository, user_id: str, content: str, course_id: str = ""
) -> Optional[dict]:
    for m in repo.list_memories(user_id, course_id):
        if (m.get("content") or "").strip() == content.strip():
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
    """新增或强化一条语义记忆（同内容去重 → REINFORCE）。"""
    now = _now_iso()
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
        return {"operation": "REINFORCE", "entity": f"memory:{existing['memory_id']}"}

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
    return {"operation": "CREATE", "entity": f"memory:{memory_id}"}


def delete_memory_direct(
    repo: LearnerRepository, user_id: str, memory_id: str
) -> Dict[str, Any]:
    """用户明确删除：真正 DELETE。"""
    repo.delete_memory(user_id, memory_id)
    return {"operation": "DELETE", "entity": f"memory:{memory_id}", "reason": "user requested"}
