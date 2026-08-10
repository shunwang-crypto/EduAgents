"""Session State：短期教学会话状态（非长期画像）。

生产：Redis key `adaptive-session:{user_id}:{course_id}:{session_id}`，带 TTL。
原型：本地 JSON（data/cache_adaptive-session-*.json），接口可替换为 Redis。

保存（短期、可立即变化）：
- current_goal_id / current_topic / current_kc
- recent_questions / re_explain_count / confusion_signal
- current_scaffold_level / current_delivery_mode
- recent_pedagogical_actions

原则：
- 不写入长期 Profile；
- Session 结束后，长期有价值信息通过 Event 回传合作伙伴，Session 本身过期即可。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from edu_agent.tools import app_state_store

DEFAULT_TTL_SECONDS = 3600  # 1 小时


class SessionStore:
    """按 user_id + course_id + session_id 保存短期会话状态。"""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds

    def _key(self, user_id: str, course_id: str, session_id: str) -> str:
        return f"cache_adaptive-session:{user_id}:{course_id}:{session_id}"

    def get(self, user_id: str, course_id: str, session_id: str) -> Dict[str, Any]:
        entry = app_state_store.load(self._key(user_id, course_id, session_id), default=None)
        if not isinstance(entry, dict):
            return {}
        if time.time() - entry.get("_created_at", 0) > self._ttl:
            return {}
        return entry.get("payload", {})

    def set(self, user_id: str, course_id: str, session_id: str, payload: Dict[str, Any]) -> None:
        app_state_store.save(
            self._key(user_id, course_id, session_id),
            {"_created_at": time.time(), "payload": payload},
        )

    def update(self, user_id: str, course_id: str, session_id: str, **fields) -> Dict[str, Any]:
        """读-改-写（会话状态更新；TTL 内有效）。"""
        current = self.get(user_id, course_id, session_id)
        current.update(fields)
        self.set(user_id, course_id, session_id, current)
        return current

    def bump_re_explain(self, user_id: str, course_id: str, session_id: str) -> int:
        """重复追问计数 +1，返回最新次数（供 Policy 使用）。"""
        current = self.get(user_id, course_id, session_id)
        count = int(current.get("re_explain_count", 0)) + 1
        self.set(user_id, course_id, session_id, {**current, "re_explain_count": count})
        return count


# Redis key 契约（生产替换说明）
#   adaptive-session:{user_id}:{course_id}:{session_id}
#   TTL: 按产品设定（原型默认 3600s）
#   内容: 见类 docstring
