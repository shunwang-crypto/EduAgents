"""Chat History / Navigation / LLM 残留 Bug 回归测试（本轮收口）。

覆盖：
- 全新课程 GET /api/chat 返回 200 + 空 history（不报错、不写库）
- General 对话被课程路由访问 → 404（复现「无法加载历史消息」根因）
- 非法 course 归属：chat 返回 404 且不产生 ghost learner_course_state
- 真实 _llm_reply 执行（不再因 requirement_block NameError 偷偷走 fallback）
- 主路径异常时 degraded context 仍含课程名 + 当前目标
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edu_agent.api.main import app  # noqa: E402
from edu_agent.application import course_service  # noqa: E402
from edu_agent.application.chat_service import ChatService  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "lm.db")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", db)
    monkeypatch.setenv("LEARNER_MODEL_USER_ID", "STU-RESIDUAL")
    from edu_agent.config.settings import get_settings

    get_settings.cache_clear()
    LearnerModelService._shared_default = None
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


# ---------------------------------------------------------------------------
def test_fresh_course_get_empty_history(client):
    """场景 A：全新课程进入 Chat → GET /api/chat 必须 200 + messages=[] + 显示 Empty State。"""
    course = client.post("/api/courses", json={"topic": "全新课程"}).json()
    cid = course["course_id"]
    r = client.get("/api/chat", params={"course_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["course_id"] == cid
    assert body["messages"] == []


def test_fresh_course_get_conversation_empty(learner):
    """GET 纯读取语义：无 conversation 时返回 conversation_id=None，不创建（无 DB write）。"""
    svc = ChatService(learner=learner)
    course = course_service.create_course("STU-FRESH", "全新课程", learner=learner)
    cid = course["course_id"]
    conv = svc.get_conversation("STU-FRESH", course_id=cid)
    assert conv["conversation_id"] is None
    assert conv["messages"] == []
    # 确认没有写入任何 conversation
    assert learner.repo.get_course_conversation("STU-FRESH", cid) is None


def test_general_conversation_course_mismatch_404(client):
    """场景 B 根因：General 对话（course_id=null）被课程路由访问 → 404。

    复现「无法加载历史消息」：前端 New Chat 创建 general conversation 却停留在
    /courses/PY/chat，导致 GET /api/chat?course_id=PY&conversation_id=CONV → ownership 不匹配。
    """
    course = client.post("/api/courses", json={"topic": "测试课程"}).json()
    cid = course["course_id"]
    r = client.post("/api/chat/conversations", json={"course_id": None})
    assert r.status_code == 200
    conv_id = r.json()["conversation_id"]
    r2 = client.get("/api/chat", params={"course_id": cid, "conversation_id": conv_id})
    assert r2.status_code == 404


def test_invalid_ownership_no_ghost_course_state(learner):
    """#16：User B 用 User A 的课程 chat → 404，且 B 不产生该课程的 ghost course_state。"""
    svc = ChatService(learner=learner)
    course_a = course_service.create_course("A", "Python", learner=learner)
    cid = course_a["course_id"]
    with pytest.raises(KeyError):
        svc.chat("B", "你好", course_id=cid)
    # 先确认归属检查发生在 ensure_course 之前：B 不应有任何该课程的 course_state
    assert learner.repo.get_course_state("B", cid) is None


def test_real_llm_reply_no_fallback(learner, monkeypatch):
    """#13/#14：真实调用 _llm_reply，不得因 requirement_block NameError 偷偷走 fallback。"""
    from langchain_core.runnables import Runnable

    class FakeMsg:
        def __init__(self, content: str) -> None:
            self.content = content

        def __str__(self) -> str:
            return self.content

    class FakeLLM(Runnable):
        def invoke(self, input, config=None, **kwargs):  # noqa: A002
            return FakeMsg("真实模型回复：Attention 通过 Query-Key 点积加权聚合 Value。")

    monkeypatch.setattr(
        "edu_agent.core.llm.get_kb_llm",
        lambda temperature=0.4, **kw: FakeLLM(),
    )
    svc = ChatService(learner=learner)
    reply = svc._llm_reply("什么是注意力机制？", "上下文", [])
    assert "真实模型回复" in reply
    assert "演示模式" not in reply  # 必须不是 fallback


def test_degraded_goal_context(learner, monkeypatch):
    """#15：主路径异常进入 degraded fallback，context 仍含课程名 + 当前目标（Goal 是 dataclass）。"""
    from edu_agent.application.chat_service import resolve_bundle_and_course

    svc = ChatService(learner=learner)
    course = course_service.create_course(
        "STU-GOAL", "Transformer 注意力机制", goal="理解 self-attention", learner=learner
    )
    cid = course["course_id"]

    def boom(*a, **k):
        raise RuntimeError("forced main path failure")

    monkeypatch.setattr(
        "edu_agent.application.chat_service.resolve_bundle_and_course", boom
    )
    ctx = svc._build_context("STU-GOAL", cid, "什么是注意力")
    assert "Transformer 注意力机制" in ctx  # 课程显示名（degraded 仍保留）
    assert "理解 self-attention" in ctx  # 当前目标（Goal dataclass 正确访问）
