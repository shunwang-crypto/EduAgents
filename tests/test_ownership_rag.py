"""本轮收口新增测试：Course ownership / Conversation ownership / RAG 真加载 /
Profile Facts → PlanContext / Course Memory / Current Goal / Progress 同步 /
三阶段边界 / kc_id 事件 / 新对话 API。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def learner(tmp_path):
    from edu_agent.learner_model.service import LearnerModelService

    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


from edu_agent.tools.course_kb import CourseKnowledgeBase  # noqa: E402


def _create(learner, user, topic, goal="两周完成分析目标"):
    from edu_agent.application.course_service import create_course

    return create_course(user, topic, goal=goal, learner=learner)


# ---------------------------------------------------------------- course ownership
def test_cross_user_course_isolation(learner):
    """A 的课程 B 不可见/不可查/不可改名/不可删。"""
    from edu_agent.application.course_service import delete_course, get_course, list_courses, rename_course

    a = _create(learner, "A", "Python 数据分析")
    b = _create(learner, "B", "Java OOP")
    # B 的列表看不到 A 的
    b_ids = {c["course_id"] for c in list_courses("B", learner)}
    assert a["course_id"] not in b_ids
    assert b["course_id"] in b_ids
    # B 访问/改名/删除 A 的课程 → KeyError
    with pytest.raises(KeyError):
        get_course("B", a["course_id"], learner)
    with pytest.raises(KeyError):
        rename_course("B", a["course_id"], "hack", learner)
    with pytest.raises(KeyError):
        delete_course("B", a["course_id"], learner)
    # A 的课程仍在
    assert get_course("A", a["course_id"], learner)["course_id"] == a["course_id"]


def test_delete_course_cascades_user_data_only(learner):
    """删除 A 的课程只清 A 的数据；同主题 B 的课程不受影响。"""
    from edu_agent.application.course_service import create_course, delete_course, get_course, list_courses
    from edu_agent.application.study_plan_service import generate_plan

    a = create_course("A", "Transformer", goal="理解原理", learner=learner)
    b = create_course("B", "Transformer", goal="从零实现", learner=learner)
    generate_plan("A", a["course_id"], goal="理解原理", learner=learner)
    generate_plan("B", b["course_id"], goal="从零实现", learner=learner)
    delete_course("A", a["course_id"], learner)
    with pytest.raises(KeyError):
        get_course("A", a["course_id"], learner)
    # B 的课程与计划完好
    assert get_course("B", b["course_id"], learner)["course_id"] == b["course_id"]
    assert learner.repo.get_plan("B", b["course_id"]) is not None


def test_same_user_same_topic_reuses_course(learner):
    from edu_agent.application.course_service import create_course

    c1 = create_course("A", "Python 数据分析", learner=learner)
    c2 = create_course("A", "Python 数据分析", goal="换目标", learner=learner)
    assert c1["course_id"] == c2["course_id"]
    assert c2["goal"]["target"] == "换目标"


# ---------------------------------------------------------------- conversation ownership
def test_conversation_ownership(learner):
    from edu_agent.application.chat_service import ChatService

    svc = ChatService(learner=learner)
    conv = svc.create_conversation("A")
    svc.chat("A", "你好", conversation_id=conv["conversation_id"])
    # B 拿 A 的 conversation → 拒绝
    with pytest.raises(KeyError):
        svc.get_conversation("B", conversation_id=conv["conversation_id"])
    with pytest.raises(KeyError):
        svc.chat("B", "hi", conversation_id=conv["conversation_id"])
    # A 的消息数不变
    msgs = svc.get_conversation("A", conversation_id=conv["conversation_id"])["messages"]
    assert len(msgs) == 2


def test_conversation_course_mismatch_rejected(learner):
    from edu_agent.application.chat_service import ChatService

    svc = ChatService(learner=learner)
    c = _create(learner, "A", "Python")
    conv = svc.create_conversation("A", course_id=c["course_id"])
    with pytest.raises(KeyError):
        svc.get_conversation("A", conversation_id=conv["conversation_id"])  # course 参数缺失 ≠ conv.course


def test_new_conversation_is_really_new(learner):
    from edu_agent.application.chat_service import ChatService

    svc = ChatService(learner=learner)
    c1 = svc.create_conversation("A")
    c2 = svc.create_conversation("A")
    assert c1["conversation_id"] != c2["conversation_id"]


# ---------------------------------------------------------------- RAG
def test_rag_loads_persisted_chunks_and_course_isolation(learner, tmp_path, monkeypatch):
    """真加载持久化 chunks；Python 问 DataFrame 命中，Java 不命中 Python chunk。"""
    import os

    from edu_agent.application.chat_service import ChatService
    from edu_agent.tools import kb_store

    # 隔离存储路径
    monkeypatch.setattr(kb_store, "STORE_PATH", tmp_path / "kb.json")
    monkeypatch.setattr(kb_store, "DATA_DIR", tmp_path)
    kb_store.clear()

    py = _create(learner, "A", "Python 数据分析")
    java = _create(learner, "A", "Java OOP")
    kb_py = CourseKnowledgeBase(user_id="A", course_id=py["course_id"])
    kb_py.load_markdown("SRC-PY", "web", "https://pandas.pydata.org", "pandas 入门",
                        "# DataFrame\n\nDataFrame 是 pandas 的核心数据结构，支持 loc/iloc 索引。")
    kb_store.replace_source_chunks("A", py["course_id"], "SRC-PY", kb_py.chunks)
    # ready gate（P1-6）：RAG 只认 metadata 存在 + status=ready 的 source，仅写 JSON chunks 不可见
    now = "2026-08-12T00:00:00Z"
    learner.repo.upsert_course_source(
        {
            "source_id": "SRC-PY",
            "user_id": "A",
            "course_id": py["course_id"],
            "source_type": "web",
            "source_url": "https://pandas.pydata.org",
            "title": "pandas 入门",
            "status": "ready",
            "import_token": "T-PY",
            "chunk_count": 1,
            "error_message": "",
            "created_at": now,
            "updated_at": now,
        }
    )

    kb_java = CourseKnowledgeBase(user_id="A", course_id=java["course_id"])
    kb_java.load_markdown("SRC-JAVA", "web", "https://docs.oracle.com", "Java OOP",
                          "# 多态\n\npolymorphism 是面向对象的核心特性。")
    kb_store.replace_source_chunks("A", java["course_id"], "SRC-JAVA", kb_java.chunks)
    learner.repo.upsert_course_source(
        {
            "source_id": "SRC-JAVA",
            "user_id": "A",
            "course_id": java["course_id"],
            "source_type": "web",
            "source_url": "https://docs.oracle.com",
            "title": "Java OOP",
            "status": "ready",
            "import_token": "T-JAVA",
            "chunk_count": 1,
            "error_message": "",
            "created_at": now,
            "updated_at": now,
        }
    )

    svc = ChatService(learner=learner)
    hits_py = svc._rag("A", py["course_id"], "DataFrame 怎么用", top_k=3)
    assert any("DataFrame" in h["text"] or "pandas" in h["title"] for h in hits_py), hits_py
    hits_java = svc._rag("A", java["course_id"], "DataFrame 怎么用", top_k=3)
    assert hits_java == [], "Java 不能命中 Python chunk"


def test_rag_empty_store_returns_empty(learner, tmp_path, monkeypatch):
    from edu_agent.application.chat_service import ChatService
    from edu_agent.tools import kb_store

    monkeypatch.setattr(kb_store, "STORE_PATH", tmp_path / "kb.json")
    monkeypatch.setattr(kb_store, "DATA_DIR", tmp_path)
    py = _create(learner, "A", "Python")
    svc = ChatService(learner=learner)
    assert svc._rag("A", py["course_id"], "DataFrame", top_k=3) == []


# ---------------------------------------------------------------- Profile Facts → PlanContext
def test_plan_context_includes_profile_facts(learner):
    from edu_agent.application.chat_service import ChatService
    from edu_agent.application.study_plan_service import generate_plan
    from edu_agent.adaptive.plan_context import build_plan_context
    from edu_agent.application.learning_context_service import resolve_bundle_and_course

    svc = ChatService(learner=learner)
    svc.chat("A", "我会 Python 基础")
    course = _create(learner, "A", "Python 数据分析", goal="两周完成分析")
    bundle, domain = resolve_bundle_and_course("A", course["course_id"], learner)
    ctx = build_plan_context(bundle, learner.repo, domain, goal="两周完成分析",
                             user_id="A", course_id=course["course_id"])
    assert any("python" in str(f).lower() or "Python" in str(f) for f in ctx["background_facts"])
    # 生成的计划 PlanContext 也带背景（走 generate_plan 内部）
    plan = generate_plan("A", course["course_id"], goal="两周完成分析", learner=learner)
    assert plan is not None and len(plan["stages"]) == 3


# ---------------------------------------------------------------- course memory
def test_course_memory_only_in_that_course(learner):
    from edu_agent.learner_model.service import LearnerModelService

    svc = LearnerModelService(repo=learner.repo, db_path="x")  # 显式 repo 复用
    # 直接经 repo 写入 course memory
    from edu_agent.learner_model.updaters import semantic_memory as mem_upd

    mem_upd.add_memory(learner.repo, "A", "接口例子对我有效", "JAVA", "experience")
    mem_upd.add_memory(learner.repo, "A", "全局偏好：喜欢动手", "", "experience")
    global_ms = [m["content"] for m in learner.repo.list_effective_memories("A", "PYTHON")]
    java_ms = [m["content"] for m in learner.repo.list_effective_memories("A", "JAVA")]
    assert "全局偏好：喜欢动手" in global_ms
    assert "接口例子对我有效" not in global_ms
    assert "接口例子对我有效" in java_ms


# ---------------------------------------------------------------- current goal
def test_current_goal_priority(learner):
    from edu_agent.learner_model.service import LearnerModelService

    svc = LearnerModelService(repo=learner.repo, db_path="x")
    course = _create(learner, "A", "Python")
    gid = course["goal"]["goal_id"]
    # 造第二个 active goal，并把 current_goal_id 指向它
    learner.upsert_goal("A", "GOAL-B", course["course_id"], name="目标B", target="B 目标")
    learner.set_current_goal("A", course["course_id"], "GOAL-B")
    bundle = learner.build_bundle("A", course["course_id"])
    assert bundle.active_goal is not None and bundle.active_goal.goal_id == "GOAL-B"


# ---------------------------------------------------------------- progress sync
def test_progress_sync_plan_course_goal(learner):
    from edu_agent.application.study_plan_service import generate_plan, update_step_status

    course = _create(learner, "A", "Python", goal="两周完成")
    plan = generate_plan("A", course["course_id"], goal="两周完成", learner=learner)
    steps = plan["steps"]
    assert len(steps) >= 3
    step = steps[0]
    update_step_status("A", course["course_id"], step["step_id"], "in_progress", learner)
    p = update_step_status("A", course["course_id"], step["step_id"], "completed", learner)
    expected = round(1 / len(steps), 3)
    assert p["progress"] == expected
    state = learner.repo.get_course_state("A", course["course_id"])
    assert state["progress"] == expected
    bundle = learner.build_bundle("A", course["course_id"])
    assert bundle.active_goal is not None and abs(bundle.active_goal.progress - expected) < 0.01


# ---------------------------------------------------------------- event kc_id
def test_step_events_use_kc_id(learner):
    from edu_agent.application.study_plan_service import generate_plan, update_step_status

    course = _create(learner, "A", "Python")
    plan = generate_plan("A", course["course_id"], learner=learner)
    step = plan["steps"][0]
    update_step_status("A", course["course_id"], step["step_id"], "in_progress", learner)
    update_step_status("A", course["course_id"], step["step_id"], "completed", learner)
    events = learner.repo.list_events("A", course["course_id"])
    started = [e for e in events if e["event_type"] == "PLAN_STEP_STARTED"]
    completed = [e for e in events if e["event_type"] == "PLAN_STEP_COMPLETED"]
    assert started and started[0]["kc_id"] == step["kc_id"]
    assert completed and completed[0]["kc_id"] == step["kc_id"]
    assert completed[0]["kc_id"] != step["step_id"]


def test_chat_event_kc_id_is_real_kc(learner):
    from edu_agent.application.chat_service import ChatService
    from edu_agent.application.study_plan_service import generate_plan

    course = _create(learner, "A", "Python")
    plan = generate_plan("A", course["course_id"], learner=learner)
    step = plan["steps"][0]
    svc = ChatService(learner=learner)
    svc.chat("A", "这个怎么学", course_id=course["course_id"], plan_step_id=step["step_id"])
    events = learner.repo.list_events("A", course["course_id"])
    sent = [e for e in events if e["event_type"] == "CHAT_MESSAGE_SENT" and e["payload_json"].find("plan_step") >= 0]
    assert sent and sent[-1]["kc_id"] == step["kc_id"]
    assert sent[-1]["kc_id"] != step["step_id"]


def test_completed_step_does_not_raise_mastery(learner):
    from edu_agent.application.study_plan_service import generate_plan, update_step_status

    course = _create(learner, "A", "Python")
    plan = generate_plan("A", course["course_id"], learner=learner)
    step = plan["steps"][0]
    update_step_status("A", course["course_id"], step["step_id"], "completed", learner)
    kc = learner.repo.get_kc("A", course["course_id"], step["kc_id"])
    assert kc is None or kc.get("mastery") is None  # completed ≠ mastered


# ---------------------------------------------------------------- three stage edge
def test_three_stage_edge_input(learner):
    from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map
    from edu_agent.workflows.study_plan.schemas import DecompositionResult, StudentInput

    decomposition = DecompositionResult(
        core_concepts=["唯一核心"],
        prerequisite_concepts=[],
        learning_sequence=["唯一核心"],
        difficulty_points=[],
        stages=[],  # 空 stages → model_validator 补默认
        application_directions=[],
    )
    km = build_knowledge_map(
        StudentInput(topic="Transformer", level=None, days=7, daily_time="60 分钟", goal="理解原理"),
        decomposition,
    )
    orders = {n.stage_order for n in km.nodes}
    assert orders == {1, 2, 3}
    assert sum(1 for n in km.nodes if n.stage_order == 1) >= 1
    assert sum(1 for n in km.nodes if n.stage_order == 2) >= 1
    assert sum(1 for n in km.nodes if n.stage_order == 3) >= 1
    # core 稳定进 Stage 2
    core_nodes = [n for n in km.nodes if n.category == "核心知识"]
    assert core_nodes and core_nodes[0].stage_order == 2


# ---------------------------------------------------------------- API smoke（fresh DB）
def test_api_smoke_ownership(learner, tmp_path, monkeypatch):
    import os

    from edu_agent.config.settings import get_settings
    from edu_agent.learner_model.service import LearnerModelService

    # 强制 offline：清空所有外部 AI / search provider 配置，
    # 让 /plan/generate 走确定性降级，而非联网真实模型（避免产生费用）。
    for key in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "XINGCHEN_API_KEY", "XINGCHEN_BASE_URL", "XINGCHEN_MODEL",
        "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_BASE_URL", "OPENCODE_ZEN_MODEL",
        "TAVILY_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", str(tmp_path / "api.db"))
    # 重置进程级单例与 settings 缓存，让上面的空配置生效，避免其他测试污染
    get_settings.cache_clear()
    LearnerModelService._shared_default = None
    from fastapi.testclient import TestClient
    from edu_agent.api.main import app

    client = TestClient(app)
    headers_a = {"X-User-Id": "A"}
    headers_b = {"X-User-Id": "B"}

    # A 建课
    r = client.post("/api/courses", json={"topic": "Python 数据分析"}, headers=headers_a)
    assert r.status_code == 200
    course_id = r.json()["course_id"]
    # A 列表有
    assert any(c["course_id"] == course_id for c in client.get("/api/courses", headers=headers_a).json())
    # B 列表无
    assert not any(c["course_id"] == course_id for c in client.get("/api/courses", headers=headers_b).json())
    # B get → 404
    assert client.get(f"/api/courses/{course_id}", headers=headers_b).status_code == 404
    # A 生成计划 → 3 阶段
    r = client.post(f"/api/courses/{course_id}/plan/generate", json={"goal": "两周完成"}, headers=headers_a)
    assert r.status_code == 200
    plan = r.json()
    assert len(plan["stages"]) == 3
    step = plan["steps"][0]
    # A PATCH step
    assert client.patch(f"/api/courses/{course_id}/plan/steps/{step['step_id']}",
                        json={"status": "in_progress"}, headers=headers_a).status_code == 200
    # 新对话 API
    r = client.post("/api/chat/conversations", json={"course_id": course_id}, headers=headers_a)
    assert r.status_code == 200
    conv_id = r.json()["conversation_id"]
    # A chat 带 conversation
    r = client.post("/api/chat", json={"message": "你好", "course_id": course_id,
                                       "conversation_id": conv_id}, headers=headers_a)
    assert r.status_code == 200
    # B 拿 A conversation → 404
    assert client.get(f"/api/chat?conversation_id={conv_id}", headers=headers_b).status_code == 404
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": conv_id},
                       headers=headers_b).status_code == 404
