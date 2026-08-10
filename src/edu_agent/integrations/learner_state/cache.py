"""LearnerStateCache：合作伙伴 LearnerState 的缓存层（非 Source of Truth）。

生产：Redis key `learner-state:{user_id}:{course_id}`，带 TTL + state_version/updated_at。
原型：本地 JSON（data/cache_learner-state-*.json），接口可替换为 Redis。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from edu_agent.tools import app_state_store


class LearnerStateCache:
    """按 user_id + course_id 缓存原始 LearnerState JSON。"""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds

    def _key(self, user_id: str, course_id: str) -> str:
        return f"cache_learner-state:{user_id}:{course_id}"

    def get(self, user_id: str, course_id: str) -> Optional[dict]:
        """返回未过期的缓存；过期/缺失返回 None。"""
        entry = app_state_store.load(self._key(user_id, course_id), default=None)
        if not isinstance(entry, dict):
            return None
        cached_at = entry.get("_cached_at", 0)
        if time.time() - cached_at > self._ttl:
            return None
        return entry.get("payload")

    def set(self, user_id: str, course_id: str, payload: Any) -> None:
        app_state_store.save(
            self._key(user_id, course_id),
            {"_cached_at": time.time(), "payload": payload},
        )

    def clear(self, user_id: str, course_id: str) -> None:
        app_state_store.clear(self._key(user_id, course_id))


# Redis key 契约（生产替换说明）
#   learner-state:{user_id}:{course_id}
#   TTL: LEARNER_STATE_CACHE_TTL_SECONDS
#   内容: {state_version, updated_at, state_freshness, payload}
