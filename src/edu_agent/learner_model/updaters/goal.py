"""Goal Updater：学习目标生命周期。

GOAL_CREATED / GOAL_UPDATED / GOAL_COMPLETED / GOAL_CANCELLED；
支持进度更新、状态流转。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_goal(
    repo: LearnerRepository,
    user_id: str,
    goal_id: str,
    course_id: str,
    name: str,
    target: str = "",
    priority: int = 1,
    target_kcs: Optional[List[str]] = None,
    deadline: str = "",
) -> Dict[str, Any]:
    """创建或更新一个目标（同 goal_id 覆盖，不重复追加）。"""
    now = _now_iso()
    existing = repo.get_goal(goal_id)
    if existing:
        repo.upsert_goal(
            {
                **existing,
                "name": name or existing.get("name"),
                "target": target or existing.get("target"),
                "target_kcs_json": json.dumps(target_kcs or [], ensure_ascii=False),
                "updated_at": now,
            }
        )
        return {"operation": "UPDATE", "entity": f"goal:{goal_id}"}
    repo.upsert_goal(
        {
            "goal_id": goal_id,
            "user_id": user_id,
            "course_id": course_id,
            "name": name,
            "target": target,
            "priority": priority,
            "status": "active",
            "progress": 0.0,
            "target_kcs_json": json.dumps(target_kcs or [], ensure_ascii=False),
            "deadline": deadline,
            "created_at": now,
            "updated_at": now,
        }
    )
    return {"operation": "CREATE", "entity": f"goal:{goal_id}"}


def set_goal_status(
    repo: LearnerRepository, goal_id: str, status: str, reason: str = ""
) -> Dict[str, Any]:
    """状态流转：active/paused/completed/cancelled。"""
    existing = repo.get_goal(goal_id)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists"}
    repo.upsert_goal({**existing, "status": status, "updated_at": _now_iso()})
    op = {"completed": "RESOLVE", "cancelled": "DEACTIVATE"}.get(status, "UPDATE")
    return {"operation": op, "entity": f"goal:{goal_id}", "reason": reason}


def update_goal_progress(
    repo: LearnerRepository, goal_id: str, progress: float
) -> Dict[str, Any]:
    """更新目标进度（0-1），达到 1.0 自动 completed。"""
    existing = repo.get_goal(goal_id)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists"}
    progress = max(0.0, min(1.0, progress))
    status = existing.get("status")
    if progress >= 1.0 and status != "completed":
        status = "completed"
    repo.upsert_goal({**existing, "progress": progress, "status": status, "updated_at": _now_iso()})
    return {
        "operation": "RESOLVE" if status == "completed" else "UPDATE",
        "entity": f"goal:{goal_id}",
        "reason": f"progress={progress:.2f}",
    }


def apply_goal_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """事件驱动的目标处理（GOAL_* 事件）。"""
    goal_id = evidence.entity_key
    if not goal_id:
        return {"operation": "NONE", "reason": "empty goal"}
    payload = evidence.payload or {}
    t = evidence.event_type
    if t == "GOAL_CREATED":
        return upsert_goal(
            repo, evidence.user_id, goal_id, evidence.course_id,
            name=payload.get("name") or goal_id,
            target=payload.get("target", ""),
            target_kcs=payload.get("target_kcs"),
        )
    if t == "GOAL_UPDATED":
        return upsert_goal(
            repo, evidence.user_id, goal_id, evidence.course_id,
            name=payload.get("name") or goal_id,
            target=payload.get("target", ""),
            target_kcs=payload.get("target_kcs"),
        )
    if t == "GOAL_COMPLETED":
        return set_goal_status(repo, goal_id, "completed", reason="GOAL_COMPLETED")
    if t == "GOAL_CANCELLED":
        return set_goal_status(repo, goal_id, "cancelled", reason="GOAL_CANCELLED")
    return {"operation": "NONE", "reason": f"unhandled {t}"}
