"""Goal Updater：学习目标生命周期（user_id + goal_id 联合身份）。

- 字段保留语义：未提供的字段保留旧值；显式空列表才清空 target_kcs。
- 支持进度更新、状态流转（active/paused/completed/cancelled）。
- scope：course（与 course_id 绑定）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.evidence_light import LightEvidence
from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_goal_id(user_id: str, course_id: str) -> str:
    """稳定且 user scoped 的 goal_id（同用户同课程同目标）。"""
    return f"GOAL-{user_id}-{course_id}"[:64]


def upsert_goal(
    repo: LearnerRepository,
    user_id: str,
    goal_id: str,
    course_id: str,
    name: str,
    target: str = "",
    priority: Optional[int] = None,
    target_kcs: Optional[List[str]] = None,
    deadline: str = "",
    status: str = "active",
) -> Dict[str, Any]:
    """创建或更新目标。未提供的字段保留旧值。"""
    now = _now_iso()
    existing = repo.get_goal(user_id, goal_id)
    if existing:
        row = dict(existing)
        if name:
            row["name"] = name
        if target:
            row["target"] = target
        if priority is not None:
            row["priority"] = priority
        if target_kcs is not None:  # 显式提供才覆盖（含清空）
            row["target_kcs_json"] = json.dumps(target_kcs, ensure_ascii=False)
        if deadline:
            row["deadline"] = deadline
        if status:
            row["status"] = status
        if target_kcs is not None:
            row["updated_at"] = now
        repo.upsert_goal(row)
        return {
            "operation": "UPDATE",
            "entity": f"goal:{goal_id}",
            "before": {"status": existing.get("status"), "progress": existing.get("progress")},
            "after": {"status": row.get("status"), "target_kcs": target_kcs},
            "reason": "upsert_goal",
            "scope": "course",
        }
    repo.upsert_goal(
        {
            "goal_id": goal_id,
            "user_id": user_id,
            "course_id": course_id,
            "name": name,
            "target": target,
            "priority": priority if priority is not None else 1,
            "status": status,
            "progress": 0.0,
            "target_kcs_json": json.dumps(target_kcs or [], ensure_ascii=False),
            "deadline": deadline,
            "created_at": now,
            "updated_at": now,
        }
    )
    return {
        "operation": "CREATE",
        "entity": f"goal:{goal_id}",
        "before": None,
        "after": {"status": status, "target_kcs": target_kcs},
        "reason": "upsert_goal",
        "scope": "course",
    }


def set_goal_status(
    repo: LearnerRepository, user_id: str, goal_id: str, status: str, reason: str = ""
) -> Dict[str, Any]:
    existing = repo.get_goal(user_id, goal_id)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "course"}
    repo.upsert_goal({**existing, "status": status, "updated_at": _now_iso()})
    op = {"completed": "RESOLVE", "cancelled": "DEACTIVATE"}.get(status, "UPDATE")
    return {
        "operation": op,
        "entity": f"goal:{goal_id}",
        "before": {"status": existing.get("status")},
        "after": {"status": status},
        "reason": reason,
        "scope": "course",
    }


def update_goal_progress(
    repo: LearnerRepository, user_id: str, goal_id: str, progress: float
) -> Dict[str, Any]:
    existing = repo.get_goal(user_id, goal_id)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "course"}
    progress = max(0.0, min(1.0, progress))
    status = existing.get("status")
    if progress >= 1.0 and status != "completed":
        status = "completed"
    repo.upsert_goal({**existing, "progress": progress, "status": status, "updated_at": _now_iso()})
    return {
        "operation": "RESOLVE" if status == "completed" else "UPDATE",
        "entity": f"goal:{goal_id}",
        "before": {"progress": existing.get("progress"), "status": existing.get("status")},
        "after": {"progress": progress, "status": status},
        "reason": f"progress={progress:.2f}",
        "scope": "course",
    }


def apply_goal_evidence(
    repo: LearnerRepository, evidence: LightEvidence
) -> Dict[str, Any]:
    """事件驱动的目标处理（GOAL_* 事件）。"""
    goal_id = evidence.entity_key
    if not goal_id:
        return {"operation": "NONE", "reason": "empty goal", "scope": "course"}
    payload = evidence.payload or {}
    t = evidence.event_type
    if t in ("GOAL_CREATED", "GOAL_UPDATED"):
        return upsert_goal(
            repo,
            evidence.user_id,
            goal_id,
            evidence.course_id,
            name=payload.get("name") or goal_id,
            target=payload.get("target", ""),
            target_kcs=payload.get("target_kcs"),
        )
    if t == "GOAL_COMPLETED":
        return set_goal_status(repo, evidence.user_id, goal_id, "completed", reason="GOAL_COMPLETED")
    if t == "GOAL_CANCELLED":
        return set_goal_status(repo, evidence.user_id, goal_id, "cancelled", reason="GOAL_CANCELLED")
    return {"operation": "NONE", "reason": f"unhandled {t}", "scope": "course"}
