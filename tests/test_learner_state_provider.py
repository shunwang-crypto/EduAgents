"""Provider 测试：mock / remote 失败降级 / 多课程隔离。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.integrations.learner_state.mock_provider import MockLearnerStateProvider  # noqa: E402
from edu_agent.integrations.learner_state.remote_provider import (  # noqa: E402
    RemoteLearnerStateProvider,
)


def test_mock_provider_returns_java_data():
    provider = MockLearnerStateProvider()
    state = provider.get_course_state("STU-001", "JAVA-OOP")
    assert state.freshness == "mock"
    assert state.progress == 0.31
    assert {k.kc_id for k in state.knowledge} >= {"CLASS", "POLYMORPHISM"}
    assert state.get_knowledge("CLASS").mastery == 0.90
    assert len(state.abilities) == 6


def test_mock_provider_goal():
    provider = MockLearnerStateProvider()
    goal = provider.get_goal("STU-001", "GOAL-JAVA-001")
    assert goal is not None
    assert goal.course_id == "JAVA-OOP"
    assert provider.get_goal("STU-001", "NOPE") is None


def test_remote_provider_falls_back_when_base_url_empty(monkeypatch):
    """未配置 base_url 时：走 mock 降级，不抛异常，业务仍可用。"""
    provider = RemoteLearnerStateProvider(base_url="", api_key="", mock_fallback=True)
    state = provider.get_course_state("STU-001", "JAVA-OOP")
    assert state.freshness == "mock"
    assert state.progress > 0


def test_remote_provider_missing_fallback_without_mock(monkeypatch):
    provider = RemoteLearnerStateProvider(base_url="", api_key="", mock_fallback=False)
    state = provider.get_course_state("STU-001", "JAVA-OOP")
    assert state.freshness == "missing"
    assert state.knowledge == []


def test_multi_course_isolation_provider(monkeypatch):
    """Java 请求不得加载 Transformer mastery（Provider 只返回 Java 数据）。"""
    provider = MockLearnerStateProvider()
    java = provider.get_course_state("STU-001", "JAVA-OOP")
    kc_ids = {k.kc_id for k in java.knowledge}
    assert "POLYMORPHISM" in kc_ids
    assert "ATTENTION" not in kc_ids
