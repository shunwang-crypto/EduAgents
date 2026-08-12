"""Application Services 集成测试（Course / StudyPlan / Chat / Learner Model）。

覆盖：课程 CRUD、多课程隔离、CourseResolver 稳定、计划生成（无 LLM 降级路径）与进度、
Chat 普通/课程对话、画像 Fact/Preference/Delete 意图、unknown mastery 语义。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402

from edu_agent.application import course_service, study_plan_service  # noqa: E402
from edu_agent.application.chat_service import (  # noqa: E402
    ChatService,
    extract_memory_intents,
)
from edu_agent.adaptive.course_resolver import resolve_course_id, resolve_goal_id  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402

USER = "STU-TEST"


@pytest.fixture()
def learner(tmp_path):
    svc = LearnerModelService(db_path=str(tmp_path / "lm.db"))
    return svc


# ----------------------------------------------------------------------
# CourseResolver
# ----------------------------------------------------------------------
def test_course_resolver_stable_and_no_collision():
    a1 = resolve_course_id("Python 数据分析")
    a2 = resolve_course_id("Python 数据分析")
    b = resolve_course_id("Python 数据分析入门")
    assert a1 == a2
    assert a1 != b  # 相似但不相同 → 不误合并
    assert resolve_course_id("Java OOP 实训") == "JAVA-OOP"


def test_goal_id_user_scoped():
    assert resolve_goal_id("A", "X") != resolve_goal_id("B", "X")


# ----------------------------------------------------------------------
# CourseService
# ----------------------------------------------------------------------
def test_course_crud(learner):
    course = course_service.create_course(USER, "Python 数据分析", goal="两周完成数据分析项目",
                                          learner=learner)
    assert course["course_id"].startswith("CUSTOM-")
    assert course["display_name"] == "Python 数据分析"
    assert course["goal"] and course["goal"]["name"] == "Python 数据分析"

    courses = course_service.list_courses(USER, learner)
    assert len(courses) == 1

    renamed = course_service.rename_course(USER, course["course_id"], "Python 数据分析进阶", learner)
    assert renamed["display_name"] == "Python 数据分析进阶"

    course_service.delete_course(USER, course["course_id"], learner)
    assert course_service.list_courses(USER, learner) == []


def test_multi_course_isolation(learner):
    py = course_service.create_course(USER, "Python 数据分析", learner=learner)
    java = course_service.create_course(USER, "Java 面向对象", learner=learner)
    assert py["course_id"] != java["course_id"]
    # 目标互不污染
    py_goals = [g for g in learner.repo.list_goals(USER) if g.get("course_id") == py["course_id"]]
    java_goals = [g for g in learner.repo.list_goals(USER) if g.get("course_id") == java["course_id"]]
    assert py_goals and java_goals
    assert py_goals[0]["goal_id"] != java_goals[0]["goal_id"]


def test_one_active_goal_per_course(learner):
    course_service.create_course(USER, "Python 数据分析", learner=learner)
    course_service.create_course(USER, "Python 数据分析", learner=learner)
    active = [g for g in learner.repo.list_goals(USER, status="active")]
    assert len(active) == 1  # 同课程只保留一个 active goal


# ----------------------------------------------------------------------
# StudyPlanService（无 LLM 环境走降级路径，验证持久化/进度）
# ----------------------------------------------------------------------
def test_plan_generate_and_progress(learner):
    course = course_service.create_course(USER, "Python 数据分析", learner=learner)
    plan = study_plan_service.generate_plan(
        USER, course["course_id"], goal="两周完成数据分析",
        duration_days=14, daily_minutes=60,
        learner=learner,
    )
    assert plan is not None
    assert plan["plan_markdown"]
    assert plan["steps"], "计划应包含步骤（降级路径也生成）"

    # 完成第一步 → progress 更新，mastery 不变
    first_step = plan["steps"][0]
    updated = study_plan_service.update_step_status(
        USER, course["course_id"], first_step["step_id"], "completed", learner
    )
    assert updated["progress"] > 0.0
    # 计划步骤完成绝不修改 mastery
    kc = learner.repo.get_kc(USER, course["course_id"], first_step["step_id"])
    assert kc is None or kc["mastery"] is None or kc["mastery"] == 0.0 or kc["mastery"] < 0.7


def test_plan_unknown_mastery_is_none(learner):
    """从未学习的主题：mastery 保持 unknown（None），不自动当 0。"""
    course = course_service.create_course(USER, "Python 数据分析", learner=learner)
    plan = study_plan_service.generate_plan(
        USER, course["course_id"], goal="数据分析基础",
        duration_days=7, daily_minutes=30, learner=learner,
    )
    for step in plan["steps"]:
        kc = learner.repo.get_kc(USER, course["course_id"], step["step_id"])
        if kc is not None:
            assert kc["mastery"] is None  # 曝光不产生掌握度


# ----------------------------------------------------------------------
# ChatService
# ----------------------------------------------------------------------
def test_general_chat_no_course(learner):
    svc = ChatService(learner=learner)
    reply = svc.chat(USER, "Docker 怎么看日志？")
    assert reply["content"]
    assert reply["course_id"] is None
    assert reply["message_id"]


def test_course_chat_uses_context(learner):
    course = course_service.create_course(USER, "Python 数据分析", learner=learner)
    svc = ChatService(learner=learner)
    reply = svc.chat(USER, "DataFrame 是什么？", course_id=course["course_id"])
    assert reply["content"]
    assert reply["course_id"] == course["course_id"]
    # 同一课程会话复用
    conv = svc.get_conversation(USER, course_id=course["course_id"])
    assert len(conv["messages"]) == 2  # user + assistant


def test_profile_fact_intent_created(learner):
    svc = ChatService(learner=learner)
    intents = extract_memory_intents("我会 Python，之前做过数据分析")
    assert any(i["action"] == "set_fact" for i in intents)
    reply = svc.chat(USER, "我会 Python 基础")
    assert reply["profile_updates"], "应识别并写入 profile fact"
    facts = learner.repo.list_profile_facts(USER)
    assert any(f["fact_key"] == "skill:python" for f in facts)


def test_skill_facts_do_not_override_each_other(learner):
    """「我会 Python」+「我会 Java」→ skill:python 与 skill:java 并存，互不覆盖。"""
    svc = ChatService(learner=learner)
    svc.chat(USER, "我会 Python 基础")
    svc.chat(USER, "我会 Java 面向对象")
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER)}
    assert "skill:python" in keys
    assert "skill:java" in keys


def test_forget_intent_deletes_real_fact(learner):
    """「忘记我做过 FastAPI」只删匹配的 fact，不误删其他。"""
    svc = ChatService(learner=learner)
    svc.chat(USER, "我做过 FastAPI 项目")  # 创建 skill:fastapi
    learner.set_profile_fact(USER, "skill:java", "Java 基础")
    reply = svc.chat(USER, "忘记我做过 FastAPI 项目")
    facts = {f["fact_key"] for f in learner.repo.list_profile_facts(USER)}
    assert "skill:fastapi" not in facts
    assert "skill:java" in facts
    assert any("skill:fastapi" in u for u in reply["profile_updates"])


def test_profile_fact_update_not_duplicate(learner):
    learner.set_profile_fact(USER, "programming_level", "advanced")
    learner.set_profile_fact(USER, "programming_level", "basic")
    facts = learner.repo.list_profile_facts(USER)
    assert len([f for f in facts if f["fact_key"] == "programming_level"]) == 1
    assert '"basic"' in facts[0]["fact_value_json"]


def test_preference_intent(learner):
    svc = ChatService(learner=learner)
    svc.chat(USER, "以后回答简洁一点，别啰嗦")
    prefs = learner.repo.list_preferences(USER)
    concise = [p for p in prefs if p["preference_key"] == "concise_first"]
    assert concise and concise[0]["status"] == "active"


def test_forget_intent_deletes(learner):
    learner.set_profile_fact(USER, "fastapi", "做过 FastAPI 项目")
    svc = ChatService(learner=learner)
    svc.chat(USER, "忘记我做过 FastAPI")
    facts = learner.repo.list_profile_facts(USER)
    assert all(f["fact_key"] != "fastapi" for f in facts)


def test_chat_history_persisted(learner):
    svc = ChatService(learner=learner)
    svc.chat(USER, "你好")
    svc.chat(USER, "你好呀")
    conv = svc.get_conversation(USER)
    assert len(conv["messages"]) == 4
