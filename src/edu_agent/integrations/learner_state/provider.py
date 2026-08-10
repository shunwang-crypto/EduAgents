"""LearnerStateProvider：业务层唯一允许访问 LearnerState 的入口。

业务 workflow 禁止直接 requests/httpx/partner raw json，统一走本接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from edu_agent.integrations.learner_state.schemas import (
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
    LearnerStateBundle,
)

class LearnerStateProvider(ABC):
    """合作伙伴 Learner Model 的统一访问接口。"""

    @abstractmethod
    def get_global_state(self, user_id: str) -> GlobalLearnerState:
        """读取用户级全局状态（profile/goals/preferences/semantic_memory）。"""

    @abstractmethod
    def get_course_state(self, user_id: str, course_id: str) -> CourseLearnerState:
        """读取某门课程的 Learner State。"""

    @abstractmethod
    def get_goal(self, user_id: str, goal_id: str) -> Goal | None:
        """读取用户某个目标（不存在返回 None）。"""

    def get_bundle(self, user_id: str, course_id: str, goal_id: str = "") -> LearnerStateBundle:
        """一次取齐业务所需的最小状态集合。"""
        global_state = self.get_global_state(user_id)
        course_state = self.get_course_state(user_id, course_id)
        goal: Goal | None = None
        if goal_id:
            goal = self.get_goal(user_id, goal_id)
        if goal is None:
            # 未指定目标时，取该课程下优先级最高的 active 目标
            for candidate in global_state.goals:
                if candidate.course_id == course_id and candidate.status == "active":
                    goal = candidate
                    break
        if goal is None and course_state.goal_id:
            goal = self.get_goal(user_id, course_state.goal_id)
        return LearnerStateBundle(
            user_id=user_id,
            course_id=course_id,
            global_state=global_state,
            course_state=course_state,
            active_goal=goal,
        )


def get_learner_state_provider(provider_name: str = "") -> LearnerStateProvider:
    """按配置返回 Provider 实例（懒加载 + 缓存）。

    配置：LEARNER_STATE_PROVIDER = mock | remote | auto
    - mock  : 固定演示数据（默认）
    - remote: 访问合作伙伴 API，失败自动降级 mock/stale
    - auto  : 配置了 LEARNER_STATE_BASE_URL 则 remote，否则 mock
    """
    from edu_agent.config.settings import get_settings

    settings = get_settings()
    name = (provider_name or settings.learner_state_provider or "auto").strip().lower()
    if name not in {"mock", "remote", "auto"}:
        name = "auto"
    if name == "remote":
        return _build_remote()
    if name == "auto":
        if settings.learner_state_base_url:
            return _build_remote()
        return _build_mock()
    return _build_mock()


_provider_cache: dict = {}


def _build_mock():
    from edu_agent.integrations.learner_state.mock_provider import MockLearnerStateProvider

    if "mock" not in _provider_cache:
        _provider_cache["mock"] = MockLearnerStateProvider()
    return _provider_cache["mock"]


def _build_remote():
    from edu_agent.integrations.learner_state.remote_provider import RemoteLearnerStateProvider

    if "remote" not in _provider_cache:
        _provider_cache["remote"] = RemoteLearnerStateProvider()
    return _provider_cache["remote"]
