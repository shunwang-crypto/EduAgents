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


# ================================================================ Final Freeze: KB 并发 + ready gate
def test_kb_store_concurrent_replace_no_lost_update(kb):
    """两个线程并发 replace 不同 source → 最终两份 chunks 都在（RLock 防 lost update）。"""
    import threading

    from edu_agent.tools import kb_store
    from edu_agent.tools.course_kb import KbChunk

    def mk(sid, n=2):
        return [KbChunk(user_id="U1", course_id="C1", source_id=sid, source_type="web",
                        source_url=f"https://e.com/{sid}", doc_title=f"doc-{sid}",
                        heading_path="h", text=f"text-{sid}-{i}") for i in range(n)]

    errors: list = []

    def worker(sid):
        try:
            for _ in range(10):
                kb_store.replace_source_chunks("U1", "C1", sid, mk(sid))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(s,)) for s in ("SRC-A", "SRC-B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    chunks = kb_store.load_chunks("U1", "C1")
    assert {c.source_id for c in chunks} == {"SRC-A", "SRC-B"}
    assert len([c for c in chunks if c.source_id == "SRC-A"]) == 2
    assert len([c for c in chunks if c.source_id == "SRC-B"]) == 2


def test_ready_gate_only_ready_sources_visible(client, kb, monkeypatch):
    """ready → 可见；failed / orphan（有 JSON 无 metadata）→ RAG 不可见（Chat/Plan/Lesson 全走 ready gate）。"""
    from edu_agent.application.course_source_service import load_ready_course_chunks

    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "RAG gate 课"},
                         headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    # 1) ready source
    r_ready = client.post(f"/api/courses/{cid}/sources",
                          json={"url": "https://example.com/ready"},
                          headers={"X-User-Id": "A"})
    assert r_ready.json()["status"] == "ready"
    ready_sid = r_ready.json()["source_id"]
    # 2) failed source：导入抛错 → status=failed 且 chunk_count=0
    monkeypatch.setattr(course_source_service, "extract_web",
                        lambda url, max_chars=1_500_000: (_ for _ in ()).throw(RuntimeError("boom")))
    r_fail = client.post(f"/api/courses/{cid}/sources",
                         json={"url": "https://example.com/fail"},
                         headers={"X-User-Id": "A"})
    assert r_fail.json()["status"] == "failed"
    assert r_fail.json()["chunk_count"] == 0  # 正式不变量：failed → chunk_count 0 → RAG inactive
    # 3) orphan chunk：直接写 JSON，无 course_sources metadata（模拟 cleanup 失败 / 旧数据）
    from edu_agent.tools import kb_store
    from edu_agent.tools.course_kb import KbChunk

    kb_store.replace_source_chunks("A", cid, "SRC-ORPHAN", [
        KbChunk(user_id="A", course_id=cid, source_id="SRC-ORPHAN", source_type="web",
                source_url="https://e.com/orphan", doc_title="orphan",
                heading_path="h", text="孤儿块内容"),
    ])
    # ready gate：只有 ready source 的 chunks 可见
    chunks = load_ready_course_chunks("A", cid)
    assert len(chunks) >= 1
    assert all(c.source_id == ready_sid for c in chunks)
    assert not any(c.source_id == r_fail.json()["source_id"] for c in chunks)
    assert not any(c.source_id == "SRC-ORPHAN" for c in chunks)


# ================================================================ Final Freeze: import generation race + FK
def test_source_generation_race_old_failure_keeps_new_ready(client, kb, monkeypatch):
    """P1-4：同 source 并发 import——旧 request 失败不得覆盖更新一代的成功（import_token guard）。"""
    import threading

    course = client.post("/api/courses", json={"topic": "Race 课"},
                         headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    url = "https://example.com/race"

    a_started, release_a = threading.Event(), threading.Event()
    state = {"calls": 0}

    def extract(url_, max_chars=1_500_000):
        state["calls"] += 1
        if state["calls"] == 1:
            a_started.set()
            release_a.wait()
            raise RuntimeError("A 失败")
        return "# Doc\n\nB GOOD 内容"

    monkeypatch.setattr(course_source_service, "extract_web", extract)

    out = {}

    def attempt():
        out["r"] = course_source_service.add_source("A", cid, url)

    t = threading.Thread(target=attempt)
    t.start()
    assert a_started.wait(5), "A 未阻塞"
    # 新代 B 成功（经 API）
    r_b = client.post(f"/api/courses/{cid}/sources", json={"url": url},
                      headers={"X-User-Id": "A"})
    assert r_b.json()["status"] == "ready"
    release_a.set()
    t.join(5)
    # 旧 A 失败不得覆盖 B：仍 ready + chunk_count=B + chunks=B 内容
    meta = client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json()[0]
    assert meta["status"] == "ready" and meta["chunk_count"] == 1, meta
    from edu_agent.tools import kb_store

    chunks = kb_store.load_chunks("A", cid)
    assert len(chunks) == 1 and "B GOOD" in chunks[0].text


def test_source_failure_cas_is_serialized_before_new_claim(client, kb, monkeypatch):
    """失败收尾与下一代 claim 串行化，旧失败不得使用新代 token。"""
    import threading
    import time

    course = client.post("/api/courses", json={"topic": "Failure CAS 课"},
                         headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    url = "https://example.com/failure-cas"
    repo = LearnerModelService().repo
    now = course_source_service._now_iso()
    claimed_a = repo.claim_course_source({
        "source_id": "SRC-FAIL-CAS", "user_id": "A", "course_id": cid,
        "source_type": "web", "source_url": url, "title": "A",
        "import_token": "TOKEN-A", "chunk_count": 0,
        "created_at": now, "updated_at": now,
    })
    assert claimed_a and claimed_a["import_token"] == "TOKEN-A"

    entered_failed_cas = threading.Event()
    release_failed_cas = threading.Event()
    original_finalize = repo.finalize_course_source_if_token

    def paused_finalize(source):
        if source.get("status") == "failed" and source.get("import_token") == "TOKEN-A":
            entered_failed_cas.set()
            assert release_failed_cas.wait(5)
        return original_finalize(source)

    monkeypatch.setattr(repo, "finalize_course_source_if_token", paused_finalize)
    old_done = threading.Event()

    def old_failure():
        course_source_service._discard_or_fail(
            repo, "A", cid, "SRC-FAIL-CAS", "TOKEN-A", RuntimeError("old failure")
        )
        old_done.set()

    old_thread = threading.Thread(target=old_failure)
    old_thread.start()
    assert entered_failed_cas.wait(5)

    new_result = {}
    new_done = threading.Event()

    from edu_agent.tools.course_kb import KbChunk
    monkeypatch.setattr(
        course_source_service,
        "_import_web",
        lambda user_id, course_id, source_id, source_url, title: [
            KbChunk(user_id=user_id, course_id=course_id, source_id=source_id,
                    source_type="web", source_url=source_url, doc_title=title,
                    heading_path="", text="B content")
        ],
    )

    def new_claim():
        new_result["row"] = course_source_service.add_source("A", cid, url, title="B")
        new_done.set()

    new_thread = threading.Thread(target=new_claim)
    new_thread.start()
    time.sleep(0.05)
    assert not new_done.is_set(), "new claim must wait for old failure CAS lock"

    release_failed_cas.set()
    old_thread.join(5)
    new_thread.join(5)
    assert old_done.is_set() and new_done.is_set()
    assert new_result["row"]["source_id"] == "SRC-FAIL-CAS"
    assert new_result["row"]["status"] == "ready"

    final = repo.get_course_source("A", cid, "SRC-FAIL-CAS")
    assert final["status"] == "ready"


def test_course_sources_fk_cascade_and_no_revive(client, kb, monkeypatch):
    """P1-5：删课程 → course_sources metadata 级联清除（DB FK 防线）；
    重建同 topic 课程 → 旧 source 不复活。"""
    _mock_web(monkeypatch)
    course = client.post("/api/courses", json={"topic": "FK 课"},
                         headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    r = client.post(f"/api/courses/{cid}/sources", json={"url": "https://example.com/fk"},
                    headers={"X-User-Id": "A"})
    assert r.json()["status"] == "ready"
    client.delete(f"/api/courses/{cid}", headers={"X-User-Id": "A"})
    # course 不存在 → sources 404（ownership）；FK CASCADE 已清 metadata
    assert client.get(f"/api/courses/{cid}/sources",
                      headers={"X-User-Id": "A"}).status_code == 404
    # 重建同 topic → 旧 source 不复活
    c2 = client.post("/api/courses", json={"topic": "FK 课"}, headers={"X-User-Id": "A"}).json()
    assert client.get(f"/api/courses/{c2['course_id']}/sources",
                      headers={"X-User-Id": "A"}).json() == []


def test_deleted_source_import_failure_returns_discarded(client, kb, monkeypatch):
    """P2：import 失败但 source 已被删除 → 返回 discarded dict（绝不 return None）。"""
    import threading

    course = client.post("/api/courses", json={"topic": "Del 课"},
                         headers={"X-User-Id": "A"}).json()
    cid = course["course_id"]
    url = "https://example.com/del3"

    started, release = threading.Event(), threading.Event()

    def extract(url_, max_chars=1_500_000):
        started.set()
        release.wait()
        raise RuntimeError("延迟失败")

    monkeypatch.setattr(course_source_service, "extract_web", extract)
    out = {}

    def attempt():
        out["r"] = course_source_service.add_source("A", cid, url)

    t = threading.Thread(target=attempt)
    t.start()
    assert started.wait(5)
    # import 期间用户删除 source
    row = client.get(f"/api/courses/{cid}/sources", headers={"X-User-Id": "A"}).json()[0]
    client.delete(f"/api/courses/{cid}/sources/{row['source_id']}",
                  headers={"X-User-Id": "A"})
    release.set()
    t.join(5)
    assert out["r"]["status"] == "discarded" and out["r"].get("source_deleted"), out
