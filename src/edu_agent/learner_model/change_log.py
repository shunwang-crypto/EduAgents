"""Profile Change Log：记录 Learner Model 每一次增删改（可解释、可回放）。

敏感删除（用户明确要求 DELETE）时，不保存被删内容的完整副本，
只记录 entity_id + operation + 时间戳的最小审计。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.repository import LearnerRepository

# 生命周期操作
OP_CREATE = "CREATE"
OP_UPDATE = "UPDATE"
OP_REINFORCE = "REINFORCE"
OP_WEAKEN = "WEAKEN"
OP_DEACTIVATE = "DEACTIVATE"
OP_REACTIVATE = "REACTIVATE"
OP_RESOLVE = "RESOLVE"
OP_DELETE = "DELETE"
OP_MERGE = "MERGE"

# 用户明确删除时，不保留完整敏感内容副本
_SENSITIVE_ENTITY_TYPES = {"profile_fact", "semantic_memory", "preference"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_change(
    repo: LearnerRepository,
    user_id: str,
    entity_type: str,
    entity_id: str,
    operation: str,
    *,
    course_id: str = "",
    before: Any = None,
    after: Any = None,
    reason: str = "",
    evidence_ids: Optional[List[str]] = None,
) -> str:
    """写入一条画像变更记录，返回 change_id。

    - 用户明确 DELETE：before/after 只存占位（不存敏感全文）。
    - 其它操作：before/after 存序列化快照（字段级，可回放）。
    """
    change_id = f"CHG-{uuid.uuid4().hex[:12]}"
    is_sensitive_delete = operation == OP_DELETE and entity_type in _SENSITIVE_ENTITY_TYPES

    before_json = None
    after_json = None
    if not is_sensitive_delete:
        before_json = json.dumps(before, ensure_ascii=False, default=str) if before is not None else None
        after_json = json.dumps(after, ensure_ascii=False, default=str) if after is not None else None

    repo.insert_change(
        {
            "change_id": change_id,
            "user_id": user_id,
            "course_id": course_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "operation": operation,
            "before_json": before_json,
            "after_json": after_json,
            "reason": reason,
            "evidence_ids_json": json.dumps(evidence_ids or [], ensure_ascii=False),
            "created_at": _now_iso(),
        }
    )
    return change_id


def list_changes(
    repo: LearnerRepository, user_id: str, course_id: str = "", limit: int = 100
) -> List[dict]:
    return repo.list_changes(user_id, course_id=course_id, limit=limit)
