"""三阶段计划 + Plan Step 上下文对话 + 一致性回归测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def learner(tmp_path):
    # 显式 db_path：get_settings() 是 lru_cache，env 方式在测试间不隔离
    from edu_agent.learner_model.service import LearnerModelService

    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


@pytest.fixture()
def seeded(learner):
    """建两个课程（PY / JAVA）+ 为 PY 生成一个三阶段计划（降级模板路径，无 LLM）。"""
    from edu_agent.application.course_service import create_course
    from edu_agent.application.study_plan_service import generate_plan, get_plan

    py = create_course("STU-001", "Python 数据分析", goal="两周完成分析项目", learner=learner)
    java = create_course("STU-002", "Java OOP", goal="掌握面向对象", learner=learner)
    learner.ensure_course("STU-002", java["course_id"])

    # 用已注册课程生成计划（workflow 无 LLM 时走降级模板，仍产出三阶段）
    plan = generate_plan("STU-001", py["course_id"], goal="两周完成分析项目",
                         duration_days=14, daily_minutes=60, learner=learner)
    return {"learner": learner, "py": py, "java": java, "plan": plan}


def test_plan_has_exactly_three_stages(seeded):
    from edu_agent.application.study_plan_service import get_plan

    plan = get_plan("STU-001", seeded["py"]["course_id"], seeded["learner"])
    assert plan is not None
    assert len(plan["stages"]) == 3
    assert [s["order"] for s in plan["stages"]] == [1, 2, 3]
    for stage in plan["stages"]:
        assert stage["stage_title"]
        assert len(stage["steps"]) >= 1  # 无空阶段


def test_plan_steps_carry_stage_and_kc(seeded):
    from edu_agent.application.study_plan_service import get_plan

    plan = get_plan("STU-001", seeded["py"]["course_id"], seeded["learner"])
    for step in plan["steps"]:
        assert step["stage_id"].startswith("stage-")
        assert 1 <= step["stage_order"] <= 3
        assert step["kc_id"]  # node.id → kc_id
        assert step["step_id"].startswith("PLANSTEP-")  # 与 kc_id 分离
        assert step["learning_objective"]
        assert step["difficulty"]


def test_step_ownership_rejected_across_courses(seeded):
    """course B + course A 的 step → 拒绝。"""
    from edu_agent.application.study_plan_service import get_step

    py_step = seeded["plan"]["steps"][0]
    java_course = seeded["java"]["course_id"]
    with pytest.raises(KeyError):
        get_step("STU-001", java_course, py_step["step_id"], seeded["learner"])


def test_step_ownership_rejected_across_users(seeded):
    """user B + user A 的 step → 拒绝。"""
    from edu_agent.application.study_plan_service import get_step

    py_step = seeded["plan"]["steps"][0]
    with pytest.raises(KeyError):
        get_step("STU-002", seeded["py"]["course_id"], py_step["step_id"], seeded["learner"])


def test_step_ownership_accepted_for_owner(seeded):
    from edu_agent.application.study_plan_service import get_step

    py_step = seeded["plan"]["steps"][0]
    step = get_step("STU-001", seeded["py"]["course_id"], py_step["step_id"], seeded["learner"])
    assert step["step_id"] == py_step["step_id"]
    assert step["title"]


def test_chat_with_plan_step_returns_plan_step_context(seeded):
    """chat(plan_step_id=...) → context.type=plan_step + step_title。"""
    from edu_agent.application.chat_service import ChatService

    step = seeded["plan"]["steps"][0]
    svc = ChatService(learner=seeded["learner"])
    reply = svc.chat("STU-001", "这个知识点怎么学？", course_id=seeded["py"]["course_id"],
                     plan_step_id=step["step_id"])
    assert reply["context"]["type"] == "plan_step"
    assert reply["context"]["plan_step_id"] == step["step_id"]
    assert reply["context"]["step_title"] == step["title"]


def test_chat_without_course_is_general(seeded):
    from edu_agent.application.chat_service import ChatService

    svc = ChatService(learner=seeded["learner"])
    reply = svc.chat("STU-001", "你好")
    assert reply["context"]["type"] == "general"


def test_chat_with_course_no_step_is_course_context(seeded):
    from edu_agent.application.chat_service import ChatService

    svc = ChatService(learner=seeded["learner"])
    reply = svc.chat("STU-001", "groupby 是什么？", course_id=seeded["py"]["course_id"])
    assert reply["context"]["type"] == "course"


def test_chat_course_not_owned_by_user_rejected(seeded):
    """STU-001 没有 java course（STU-002 的）→ chat 拒绝（KeyError → 404）。"""
    from edu_agent.application.chat_service import ChatService

    step = seeded["plan"]["steps"][0]
    java_course = seeded["java"]["course_id"]
    svc = ChatService(learner=seeded["learner"])
    with pytest.raises(KeyError):
        svc.chat("STU-001", "你好", course_id=java_course, plan_step_id=step["step_id"])


def test_rag_query_uses_message_not_empty(seeded, monkeypatch):
    """正式路径 RAG query = step.title + message，绝不允许空串。"""
    from edu_agent.application import chat_service as cs

    captured: dict = {}
    class FakeKB:
        chunks = [object()]  # 非空 → 触发检索

        def __init__(self, *a, **kw):
            pass

        def search(self, query, top_k=3):
            captured["query"] = query
            captured["top_k"] = top_k
            return []

    monkeypatch.setattr(cs, "CourseKnowledgeBase", FakeKB, raising=False)
    # 直接替换 _rag 内部 import 的类：通过 monkeypatch module 内引用不可行，
    # 改测 _build_context 触发 _rag（course_kb import 失败会走 [] 分支，这里用可控方式）
    step = seeded["plan"]["steps"][0]
    svc = cs.ChatService(learner=seeded["learner"])
    svc._rag = lambda cid, msg, top_k=3: (captured.update(query=msg, top_k=top_k) or [])
    svc._build_context("STU-001", seeded["py"]["course_id"], "为什么这样？", step)
    assert captured["query"]
    assert captured["query"] != ""
    assert "为什么这样" in captured["query"]
    assert step["title"] in captured["query"]
    assert captured["top_k"] == 3


def test_message_metadata_records_step(seeded):
    from edu_agent.application.chat_service import ChatService

    step = seeded["plan"]["steps"][0]
    svc = ChatService(learner=seeded["learner"])
    svc.chat("STU-001", "讲讲", course_id=seeded["py"]["course_id"], plan_step_id=step["step_id"])
    conv = svc.get_conversation("STU-001", course_id=seeded["py"]["course_id"])
    user_msg = conv["messages"][0]
    assert user_msg["metadata"]["plan_step_id"] == step["step_id"]
    assert user_msg["metadata"]["step_title"] == step["title"]


def test_regenerate_replaces_old_plan(seeded):
    """重新生成 → 旧 plan 被替换（每课程一个 current plan），不无限累积。"""
    from edu_agent.application.study_plan_service import generate_plan, get_plan

    first = seeded["plan"]
    second = generate_plan("STU-001", seeded["py"]["course_id"], goal="两周完成分析项目",
                           duration_days=10, daily_minutes=45, learner=seeded["learner"])
    assert second["plan_id"] != first["plan_id"]
    repo = seeded["learner"].repo
    old_steps = repo.list_plan_steps(first["plan_id"])
    assert old_steps == []  # 旧 plan 步骤已删
    assert repo.get_plan("STU-001", seeded["py"]["course_id"])["plan_id"] == second["plan_id"]
    assert len(second["stages"]) == 3
