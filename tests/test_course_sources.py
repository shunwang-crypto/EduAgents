"""Course Sources（Web / GitHub / Internet Search）端到端测试。

覆盖：空列表 / Web 抓取就绪 / GitHub 导入就绪 / 用户+课程双隔离（最关键）/
重复 URL 复用 / 失败标记 / 失败重试 / 删除清 chunks / 删除课程级联清资料 /
互联网搜索候选（不导入）/ 计划 knowledge_context 注入。

外部导入（Tavily / GitHub clone）一律 monkeypatch，整库离线、零真实网络。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edu_agent.api.main import app  # noqa: E402
from edu_agent.application import course_source_service  # noqa: E402
from edu_agent.config.settings import get_settings  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402
from edu_agent.tools import kb_store  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "lm.db")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", db)
    monkeypatch.setenv("LEARNER_MODEL_USER_ID", "DEV")
    for key in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "XINGCHEN_API_KEY", "XINGCHEN_BASE_URL", "XINGCHEN_MODEL",
        "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_BASE_URL", "OPENCODE_ZEN_MODEL",
        "TAVILY_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    LearnerModelService._shared_default = None
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    LearnerModelService._shared_default = None


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    """隔离 kb_store 持久化路径，避免污染其它测试。"""
    monkeypatch.setattr(kb_store, "STORE_PATH", tmp_path / "kb.json")
    monkeypatch.setattr(kb_store, "DATA_DIR", tmp_path)
    kb_store.clear()
    yield


def _mock_web(monkeypatch, text="# Doc\n\nKNOWLEDGE_MARKER_xyz 是测试标记内容。"):
    monkeypatch.setattr(
        course_source_service, "extract_web",
        lambda url, max_chars=1_500_000: text,
    )


def _mock_github(monkeypatch, docs=None):
    docs = docs or {
        "README.md": "# Repo\n\n## Install\n\npip install demo。",
        "guide.md": "# Guide\n\n常见问题先看日志。",
    }
    monkeypatch.setattr(
        course_source_service, "import_github_repo",
        lambda url, **kw: dict(docs),
    )


# ---------------------------------------------------------------- 空列表
def test_list_sources_empty(client, kb):
    course = client.post("/api/courses", json={"topic": "空资料课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    assert client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json() == []


# ---------------------------------------------------------------- Web 抓取就绪
def test_add_web_source_ready(client, kb, monkeypatch):
    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "Web 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/doc"},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "web"
    assert body["chunk_count"] >= 1
    # 列表可见
    sources = client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json()
    assert len(sources) == 1 and sources[0]["source_id"] == body["source_id"]
    # chunks 已落库（user+course 隔离）
    chunks = kb_store.load_chunks("A", cid)
    assert len(chunks) == body["chunk_count"]


# ---------------------------------------------------------------- GitHub 导入就绪
def test_add_github_source_ready(client, kb, monkeypatch):
    _mock_github(monkeypatch)
    course = client.post("/api/courses", json={"topic": "GitHub 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://github.com/owner/repo"},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "github"
    assert body["chunk_count"] >= 1


# ---------------------------------------------------------------- 用户+课程双隔离（最关键）
def test_user_course_isolation(client, kb, monkeypatch):
    _mock_web(monkeypatch)
    # A 建课 C1 并加资料
    c1 = client.post("/api/courses", json={"topic": "A 的课"}, headers={"X-User-Id": "A"}).json()
    cid = c1["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/a-doc"},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200
    sid = r.json()["source_id"]

    # B 列 A 的课 → 404（ownership）
    assert client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "B"}).status_code == 404
    # B 往 A 的课加资料 → 404
    assert client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/b-hack"},
        headers={"X-User-Id": "B"},
    ).status_code == 404

    # B 的 chunks 完全看不到 A 的资料
    assert kb_store.load_chunks("B", cid) == []
    # A 本人在 C1 的 chunks 存在
    assert len(kb_store.load_chunks("A", cid)) >= 1

    # A 的 C1 资料不能泄漏到 A 的其它课程 C2
    c2 = client.post("/api/courses", json={"topic": "A 的课2"}, headers={"X-User-Id": "A"}).json()
    cid2 = c2["course_id"]
    assert client.get(f"/api/courses/{cid2}/sources", headers={"X-User-Id": "A"}).json() == []
    assert kb_store.load_chunks("A", cid2) == []


# ---------------------------------------------------------------- 重复 URL 复用 source_id
def test_dedup_same_url_reuses_source_id(client, kb, monkeypatch):
    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "Dedup 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    url = "https://example.com/same"
    r1 = client.post(f"/api/courses/{cid}/sources", json={"url": url}, headers={"X-User-Id": "A"})
    r2 = client.post(f"/api/courses/{cid}/sources", json={"url": url}, headers={"X-User-Id": "A"})
    assert r1.status_code == 200 and r2.status_code == 200
    # 同一 source_id 复用（replace 语义，不 A/A 叠加）
    assert r1.json()["source_id"] == r2.json()["source_id"]
    assert r2.json()["status"] == "ready"
    # 列表只有一条
    sources = client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json()
    assert len(sources) == 1


# ---------------------------------------------------------------- 失败标记（不泄露内部信息）
def test_add_web_source_failed(client, kb, monkeypatch):
    monkeypatch.setattr(
        course_source_service, "extract_web",
        lambda url, max_chars=1_500_000: (_ for _ in ()).throw(RuntimeError("tavily 500 traceback /api/key/secret")),
    )
    course = client.post("/api/courses", json={"topic": "Fail 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/broken"},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0
    # 失败信息可读，且不泄露内部细节（api key / traceback）
    assert "key" not in body["error_message"].lower()
    assert "traceback" not in body["error_message"].lower()
    # 失败不落盘 chunks
    assert kb_store.load_chunks("A", cid) == []


# ---------------------------------------------------------------- 失败重试 → ready
def test_retry_failed_source(client, kb, monkeypatch):
    state = {"ok": False}
    def _extract(url, max_chars=1_500_000):
        if not state["ok"]:
            raise RuntimeError("临时失败")
        return "# Doc\n\n重试成功内容。"
    monkeypatch.setattr(course_source_service, "extract_web", _extract)

    course = client.post("/api/courses", json={"topic": "Retry 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    url = "https://example.com/retry"
    r1 = client.post(f"/api/courses/{cid}/sources", json={"url": url}, headers={"X-User-Id": "A"})
    assert r1.json()["status"] == "failed"
    # 恢复可用，重试同一 URL
    state["ok"] = True
    r2 = client.post(f"/api/courses/{cid}/sources", json={"url": url}, headers={"X-User-Id": "A"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"
    assert r2.json()["source_id"] == r1.json()["source_id"]


# ---------------------------------------------------------------- 删除清 chunks
def test_delete_source_clears_chunks(client, kb, monkeypatch):
    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "Del 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/del"},
        headers={"X-User-Id": "A"},
    )
    sid = r.json()["source_id"]
    assert len(kb_store.load_chunks("A", cid)) >= 1

    assert client.delete(
        f"/api/courses/{cid}/sources/{sid}", headers={"X-User-Id": "A"}
    ).status_code == 204
    # 列表空 + chunks 清
    assert client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json() == []
    assert kb_store.load_chunks("A", cid) == []


# ---------------------------------------------------------------- 删除课程级联清资料 + chunks
def test_delete_course_cascades_sources(client, kb, monkeypatch):
    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "Cascade 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/cascade"},
        headers={"X-User-Id": "A"},
    )
    assert len(kb_store.load_chunks("A", cid)) >= 1

    assert client.delete(f"/api/courses/{cid}", headers={"X-User-Id": "A"}).status_code == 204
    # 课程已删 → 列资料 404
    assert client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).status_code == 404
    # chunks 已随课程清除
    assert kb_store.load_chunks("A", cid) == []


# ---------------------------------------------------------------- 互联网搜索候选（不导入）
def test_search_internet_returns_candidates(client, kb, monkeypatch):
    monkeypatch.setattr(
        course_source_service, "search_internet",
        lambda query, limit=5: [
            {"title": "结果一", "url": "https://example.com/1", "snippet": "摘要一"},
            {"title": "结果二", "url": "https://example.com/2", "snippet": "摘要二"},
        ],
    )
    course = client.post("/api/courses", json={"topic": "Search 课"}, headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.get(
        f"/api/courses/{cid}/sources/search",
        params={"q": "python 教程", "limit": 5},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200, r.text
    results = r.json()
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/1"
    # 搜索不直接导入：资料列表仍空
    assert client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json() == []


# ---------------------------------------------------------------- 计划 knowledge_context 注入
def test_plan_knowledge_context_includes_source(client, kb, monkeypatch):
    import edu_agent.application.study_plan_service as sp

    # 检索 query = f"{semantic_topic} {goal_text}"，搜索要求命中数 >= min_hits(2)；
    # mock 文本必须包含 query 的多个 token（课程名/目标词），否则命中不足检索为空。
    _mock_web(monkeypatch, text="# Doc\n\n知识注入课资料：理解 KNOWLEDGE_MARKER_xyz 原理，标记为测试内容。")
    captured = {}
    orig = sp.run_study_plan_workflow

    def _spy(student_input, plan_context="", knowledge_context="无"):
        captured["knowledge_context"] = knowledge_context
        return orig(student_input, plan_context=plan_context, knowledge_context=knowledge_context)

    monkeypatch.setattr(sp, "run_study_plan_workflow", _spy)

    # goal 含标记词，保证检索命中源 chunk
    course = client.post(
        "/api/courses",
        json={"topic": "知识注入课"},
        headers={"X-User-Id": "A"},
    ).json()
    cid = course["course_id"]
    r = client.post(
        f"/api/courses/{cid}/sources",
        json={"url": "https://example.com/knowledge"},
        headers={"X-User-Id": "A"},
    )
    assert r.json()["status"] == "ready"

    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"goal": "理解 KNOWLEDGE_MARKER_xyz 原理"},
        headers={"X-User-Id": "A"},
    )
    assert r.status_code == 200, r.text
    # knowledge_context 已注入源资料内容（不再是无）
    assert "KNOWLEDGE_MARKER_xyz" in captured["knowledge_context"]
