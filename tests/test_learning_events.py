"""LearningEvent 测试：事件构造 / Outbox 幂等 / 投递失败不阻塞。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.integrations.learner_state import event_emitter  # noqa: E402
from edu_agent.integrations.learner_state.event_emitter import (  # noqa: E402
    build_event,
    emit_event,
    flush_outbox,
    LearningEvent,
)


def _reset_outbox(tmp_path, monkeypatch):
    from edu_agent.tools import app_state_store

    # 动态 key（cache_*/learning_event_*）走 DATA_DIR，必须一并重定向
    monkeypatch.setattr(app_state_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        app_state_store,
        "_FILES",
        {key: tmp_path / path.name for key, path in app_state_store._FILES.items()},
    )


def test_build_event_defaults_strength(tmp_path, monkeypatch):
    _reset_outbox(tmp_path, monkeypatch)
    ev = build_event("SELF_REPORTED_UNDERSTANDING", user_id="U1", course_id="JAVA-OOP")
    assert ev.evidence_strength == "weak"
    assert ev.meaningful_for_profile is True  # 在 MEANINGFUL_FOR_PROFILE 集合内
    ev2 = build_event("COURSE_OPENED", user_id="U1")
    assert ev2.meaningful_for_profile is False


def test_event_idempotent_outbox(tmp_path, monkeypatch):
    _reset_outbox(tmp_path, monkeypatch)
    ev = build_event("EXPLANATION_REQUESTED", user_id="U1", kc_id="POLYMORPHISM")
    eid1 = emit_event(ev)
    eid2 = emit_event(ev)  # 同 event_id 不重复
    assert eid1 == eid2
    outbox = event_emitter._load_outbox()
    assert len(outbox) == 1


def test_flush_failure_keeps_event_in_outbox(tmp_path, monkeypatch):
    """合作伙伴 API 不可用：主请求不受影响，事件留在 outbox 等待重试。"""
    _reset_outbox(tmp_path, monkeypatch)
    emit_event(build_event("EXPLANATION_DELIVERED", user_id="U1"))
    # 空 delivery_url = 投递不可用
    result = flush_outbox(delivery_url=None)
    assert result["delivered"] == 0
    outbox = event_emitter._load_outbox()
    assert len(outbox) == 1
    assert outbox[0]["delivery_state"] in ("pending",)


def test_flush_marks_failed_after_max_attempts(tmp_path, monkeypatch):
    _reset_outbox(tmp_path, monkeypatch)
    emit_event(build_event("TOPIC_COMPLETED", user_id="U1"))
    # 用不可达的 URL（本机未监听端口），投递必然失败
    result = flush_outbox(delivery_url="http://127.0.0.1:1/events", timeout=0.5, max_attempts=1)
    assert result["delivered"] == 0
    assert result["failed"] == 1
