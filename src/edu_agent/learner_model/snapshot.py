"""Learner State Snapshot：画像版本快照（调试/回放/实验）。

不每个 Event 都生成快照；由 service 在「累计 N 个有意义事件」或
「重要状态变更」后调用 maybe_snapshot()。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def take_snapshot(
    repo: LearnerRepository,
    user_id: str,
    course_id: str,
    state_version: int,
    snapshot_data: Dict[str, Any],
) -> str:
    """保存一份完整画像快照，返回 snapshot_id。"""
    snapshot_id = f"SNAP-{uuid.uuid4().hex[:12]}"
    repo.insert_snapshot(
        {
            "snapshot_id": snapshot_id,
            "user_id": user_id,
            "course_id": course_id,
            "state_version": state_version,
            "snapshot_json": json.dumps(snapshot_data, ensure_ascii=False, default=str),
            "created_at": _now_iso(),
        }
    )
    return snapshot_id


def maybe_snapshot(
    repo: LearnerRepository,
    user_id: str,
    course_id: str,
    state_version: int,
    snapshot_data: Dict[str, Any],
    interval: int = 10,
) -> Optional[str]:
    """每累计 interval 个课程事件生成一次快照。"""
    count = repo.count_events(user_id, course_id)
    if count > 0 and count % interval == 0:
        return take_snapshot(repo, user_id, course_id, state_version, snapshot_data)
    return None
