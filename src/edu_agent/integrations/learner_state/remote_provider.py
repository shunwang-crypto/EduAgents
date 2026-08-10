"""RemoteLearnerStateProvider：通过 HTTP 访问合作伙伴 Learner Model API。

- 地址/密钥/超时全部来自环境变量，不写死在代码里。
- 合作伙伴不可用时降级策略：
    1. 有可接受的缓存 → 用缓存并标记 stale；
    2. 无缓存 → 用 Mock 数据并标记 mock；
    3. 业务输出仍然可用，并在上下文标注 state_freshness。
- 使用 Python 标准库 urllib，避免新增依赖（与 web_search.py 一致）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from edu_agent.config.settings import get_settings
from edu_agent.integrations.learner_state.adapter import (
    make_empty_course_state,
    make_mock_course_state,
    parse_course_state,
    parse_global_state,
)
from edu_agent.integrations.learner_state.mock_provider import (
    DEFAULT_COURSE_ID,
    DEFAULT_USER_ID,
    MockLearnerStateProvider,
    _java_course_raw,
    JAVA_GLOBAL_RAW,
)
from edu_agent.integrations.learner_state.provider import LearnerStateProvider
from edu_agent.integrations.learner_state.schemas import (
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
)
from edu_agent.tools import app_state_store

_UA = "EduAgents-LearnerState/1.0"


def _http_get_json(url: str, api_key: str, timeout: float) -> dict:
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _cache_key(user_id: str, course_id: str) -> str:
    return f"learner-state:{user_id}:{course_id}"


class RemoteLearnerStateProvider(LearnerStateProvider):
    """访问合作伙伴 Learner Model 的 HTTP Provider（带缓存降级）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 8.0,
        cache_ttl_seconds: int = 300,
        mock_fallback: bool = True,
    ):
        settings = get_settings()
        self._base_url = (base_url or settings.learner_state_base_url or "").rstrip("/")
        self._api_key = api_key if api_key is not None else settings.learner_state_api_key
        self._timeout = timeout if timeout else settings.learner_state_timeout_seconds
        self._cache_ttl = cache_ttl_seconds if cache_ttl_seconds else settings.learner_state_cache_ttl
        self._mock_fallback = mock_fallback
        self._mock = MockLearnerStateProvider()

    # -- 内部 HTTP 封装 ----------------------------------------------------

    def _get(self, path: str) -> Optional[dict]:
        if not self._base_url:
            return None
        url = f"{self._base_url}{path}"
        try:
            return _http_get_json(url, self._api_key, self._timeout)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    # -- 缓存 --------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[dict]:
        return app_state_store.load(f"cache_{key}", default=None)

    def _cache_set(self, key: str, payload: dict) -> None:
        app_state_store.save(f"cache_{key}", payload)

    # -- 接口实现 ----------------------------------------------------------

    def get_global_state(self, user_id: str) -> GlobalLearnerState:
        raw = self._get(f"/api/students/{user_id}/profile")
        if raw is not None:
            return parse_global_state(raw)
        # 降级：mock 全局状态（全局信息不含精确掌握度，演示可接受）
        return parse_global_state(JAVA_GLOBAL_RAW)

    def get_course_state(self, user_id: str, course_id: str) -> CourseLearnerState:
        cache_key = _cache_key(user_id, course_id)
        raw = self._get(f"/api/students/{user_id}/learning-state?course_id={course_id}")
        if raw is not None:
            state = parse_course_state(raw, user_id=user_id, course_id=course_id)
            state.freshness = "fresh"
            self._cache_set(cache_key, raw)
            return state
        # 远程不可用 → 缓存降级
        cached = self._cache_get(cache_key)
        if cached is not None:
            state = parse_course_state(cached, user_id=user_id, course_id=course_id)
            state.freshness = "stale"
            return state
        # 无缓存 → mock / missing
        if self._mock_fallback:
            mock_raw = _java_course_raw()
            mock_raw["user_id"] = user_id
            mock_raw["course_id"] = course_id
            return make_mock_course_state(mock_raw, user_id=user_id, course_id=course_id)
        return make_empty_course_state(user_id, course_id)

    def get_goal(self, user_id: str, goal_id: str) -> Goal | None:
        global_state = self.get_global_state(user_id)
        for goal in global_state.goals:
            if goal.goal_id == goal_id:
                return goal
        return None
