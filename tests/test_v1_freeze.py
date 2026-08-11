"""EduAgents V1 Freeze Pass 回归测试。

覆盖用户 Freeze Acceptance 的核心正确性项：
- Chat 当前消息只进 Prompt 一次 / recent history 最近 N 条
- plan_step_id 显式无效 → 404（不静默降级）
- Fact 人类可读 / 正负冲突互消 / 多技能不按空格拆 / forget 边界
- Memory scope（course 不强化 global / course 优先 / delete 校验）
- Goal updated_at / no-op / active goal priority fallback
- apply_event 并发幂等
- 三阶段全非空 + 顺序
- Plan finalize 事务 / 每课程一个 plan UNIQUE / progress CHECK
- Course delete 事件原子
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402

from edu_agent.application import course_service  # noqa: E402
from edu_agent.application.chat_service import ChatService, _split_skills, extract_memory_intents  # noqa: E402
from edu_agent.application.study_plan_service import generate_plan  # noqa: E402
from edu_agent.learner_model.fact_text import humanize_profile_fact, parse_fact_value_json  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402
from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map  # noqa: E402
from edu_agent.workflows.study_plan.schemas import (  # noqa: E402
    DecompositionResult,
    LearningStageSuggestion,
    StudentInput,
)

USER = "STU-FREEZE"


@pytest.fixture()
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


def _stages():
    return [
        LearningStageSuggestion(stage_id="stage-1", title="基础准备", objective="o", order=1),
        LearningStageSuggestion(stage_id="stage-2", title="核心学习", objective="o", order=2),
        LearningStageSuggestion(stage_id="stage-3", title="综合应用", objective="o", order=3),
    ]


def _make_course(learner, user_id=USER, topic="Python 数据分析"):
    return course_service.create_course(user_id, topic, learner=learner)


# ---------------------------------------------------------------- 1. Chat prompt once
def test_chat_current_message_only_once_in_prompt(learner):
    course = _make_course(learner)
    svc = ChatService(learner=learner)
    captured = {}

    def fake_reply(message, context_text, history):
        captured["message"] = message
        captured["history"] = history
        return "OK 回复"

    svc._llm_reply = fake_reply  # type: ignore[method-assign]
    svc.chat(USER, "Attention 为什么要除以 sqrt(dk)？", course_id=course["course_id"])
    assert captured["message"] == "Attention 为什么要除以 sqrt(dk)？"
    # history 是 PRIOR history，不含当前消息 → Prompt 中当前消息只出现一次
    assert not any(h["content"] == captured["message"] for h in captured["history"])
    # 第二条消息时 history 含第一条但仍是 prior
    captured2 = {}
    svc._llm_reply = lambda m, c, h: captured2.update(message=m, history=h) or "OK"  # type: ignore[method-assign]
    svc.chat(USER, "再问一次", course_id=course["course_id"])
    assert captured2["message"] == "再问一次"
    assert not any(h["content"] == "再问一次" for h in captured2["history"])


# ---------------------------------------------------------------- 2. recent history latest N
def test_recent_history_returns_latest_n_chronological(learner):
    course = _make_course(learner)
    svc = ChatService(learner=learner)
    conv_row = svc.create_conversation(USER, course["course_id"])
    conv = learner.repo.get_conversation(conv_row["conversation_id"])
    for i in range(1, 21):
        learner.repo.insert_message(
            {"message_id": f"MSG-{i:02d}", "conversation_id": conv["conversation_id"],
             "role": "user" if i % 2 else "assistant", "content": f"消息{i}",
             "created_at": f"2026-08-11T{i:02d}:00:00Z", "metadata_json": "{}"}
        )
    recent = learner.repo.list_recent_messages(conv["conversation_id"], limit=8)
    contents = [m["content"] for m in recent]
    assert contents == [f"消息{i}" for i in range(13, 21)]
    # 不能是最早 8 条
    assert "消息1" not in contents


# ---------------------------------------------------------------- 3. invalid plan_step → 404
def test_invalid_plan_step_id_raises(learner):
    course = _make_course(learner)
    plan = generate_plan(USER, course["course_id"], learner=learner)
    svc = ChatService(learner=learner)
    svc._llm_reply = lambda m, c, h: "OK"  # type: ignore[method-assign]
    # 不属于本课程/本用户的 step id
    with pytest.raises(KeyError):
        svc.chat(USER, "hi", course_id=course["course_id"], plan_step_id="PLANSTEP-不存在")
    # 合法 step 正常
    step_id = plan["steps"][0]["step_id"]
    reply = svc.chat(USER, "hi", course_id=course["course_id"], plan_step_id=step_id)
    assert reply["context"]["type"] == "plan_step"


# ---------------------------------------------------------------- 4. rename → chat course_title
def test_rename_appears_in_chat_context(learner):
    course = _make_course(learner, topic="Python 数据分析")
    course_service.rename_course(USER, course["course_id"], "Py 数据科学课", learner=learner)
    svc = ChatService(learner=learner)
    ctx = svc._build_context(USER, course["course_id"], "hello", None)
    assert "Py 数据科学课" in ctx
    assert "CUSTOM-" not in ctx


# ---------------------------------------------------------------- 5. fact humanized
def test_profile_facts_humanized(learner):
    learner.set_profile_fact(USER, "skill:python", "Python 数据分析")
    learner.set_profile_fact(USER, "no_java", {"level": "none"})
    assert humanize_profile_fact("skill:python", '"Python 数据分析"') == "已掌握 python"
    assert humanize_profile_fact("no_java", '{"level":"none"}') == "无 java 基础"
    assert parse_fact_value_json('"Python"') == "Python"  # 不带 JSON 引号


# ---------------------------------------------------------------- 6/7. memory scope
def test_course_memory_before_global_and_no_cross_reinforce(learner):
    learner.add_memory(USER, "全局记忆内容")
    learner.add_memory(USER, "课程记忆内容", course_id="C-1")
    eff = [m["content"] for m in learner.repo.list_effective_memories(USER, "C-1")]
    # course 优先
    assert eff[0] == "课程记忆内容"
    # course 添加同内容不强化 global
    before_global = learner.repo.list_global_memories(USER)[0]
    learner.add_memory(USER, "课程记忆内容", course_id="C-1")
    global_rows = learner.repo.list_global_memories(USER)
    assert len(global_rows) == 1
    assert global_rows[0]["content"] == "全局记忆内容"
    assert before_global["importance"] == global_rows[0]["importance"]


def test_delete_memory_scope_and_missing(learner):
    learner.add_memory(USER, "课程记忆A", course_id="C-1")
    mem = learner.repo.list_course_memories(USER, "C-1")[0]
    result = learner.delete_memory(USER, mem["memory_id"])
    assert result["operation"] == "DELETE"
    assert result["scope"] == "course"
    # 不存在 → NONE
    result2 = learner.delete_memory(USER, "MEM-不存在")
    assert result2["operation"] == "NONE"


# ---------------------------------------------------------------- 8/9. skill contradiction
def test_skill_contradiction_pos_then_neg(learner):
    learner.set_profile_fact(USER, "skill:python", "Python")
    learner.set_profile_fact(USER, "no_python", {"level": "none"})
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER) if f.get("status") == "active"}
    assert "skill:python" not in keys
    assert "no_python" in keys


def test_skill_contradiction_neg_then_pos(learner):
    learner.set_profile_fact(USER, "no_python", {"level": "none"})
    learner.set_profile_fact(USER, "skill:python", "Python")
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER) if f.get("status") == "active"}
    assert "no_python" not in keys
    assert "skill:python" in keys


# ---------------------------------------------------------------- 10/11. skill split
def test_python_data_analysis_not_split_by_space(learner):
    intents = extract_memory_intents("我会 Python 数据分析")
    skills = [i["fact_key"] for i in intents if i["action"] == "set_fact"]
    assert skills == ["skill:python"]  # 一个技能短语，不按空格拆


def test_python_and_java_splits_two():
    assert _split_skills("Python 和 Java") == ["Python", "Java"]
    assert _split_skills("Python 数据分析") == ["Python 数据分析"]


# ---------------------------------------------------------------- 12. forget boundary
def test_forget_java_keeps_javascript(learner):
    learner.set_profile_fact(USER, "skill:javascript", "JavaScript 前端")
    svc = ChatService(learner=learner)
    svc._llm_reply = lambda m, c, h: "OK"  # type: ignore[method-assign]
    svc.chat(USER, "忘记我做过 Java 项目", course_id=None)
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER)}
    assert "skill:javascript" in keys  # java 不得命中 javascript


# ---------------------------------------------------------------- 13/14. goal
def test_goal_updated_at_and_noop(learner):
    course = _make_course(learner)
    learner.upsert_goal(USER, "GOAL-1", course["course_id"], name="目标", target="t1", priority=1)
    row1 = learner.repo.get_goal(USER, "GOAL-1")
    # 无变化 → NONE，不更新时间
    r = learner.upsert_goal(USER, "GOAL-1", course["course_id"], name="目标", target="t1", priority=1)
    assert r["operation"] == "NONE"
    row2 = learner.repo.get_goal(USER, "GOAL-1")
    assert row2["updated_at"] == row1["updated_at"]
    # 任意字段变化 → updated_at 更新
    learner.upsert_goal(USER, "GOAL-1", course["course_id"], name="新目标")
    row3 = learner.repo.get_goal(USER, "GOAL-1")
    assert row3["updated_at"] > row1["updated_at"]
    assert row3["name"] == "新目标"
    # status=None 不复活 paused goal
    learner.set_goal_status(USER, "GOAL-1", "paused")
    r4 = learner.upsert_goal(USER, "GOAL-1", course["course_id"], name="新目标2")
    assert r4["operation"] == "UPDATE"
    assert learner.repo.get_goal(USER, "GOAL-1")["status"] == "paused"


def test_active_goal_priority_fallback(learner):
    course = _make_course(learner)
    # 关闭 create_course 建立的默认 current goal
    default_goal = course["goal"]["goal_id"]
    learner.set_goal_status(USER, default_goal, "paused")
    learner.upsert_goal(USER, "GOAL-A", course["course_id"], name="A", target="tA", priority=5)
    learner.upsert_goal(USER, "GOAL-B", course["course_id"], name="B", target="tB", priority=1)
    learner.upsert_goal(USER, "GOAL-C", course["course_id"], name="C", target="tC", priority=2)
    goal = learner.resolve_active_goal(USER, course["course_id"])
    assert goal.goal_id == "GOAL-B"  # priority 小优先
    # current_goal_id 优先
    learner.set_current_goal(USER, course["course_id"], "GOAL-C")
    goal2 = learner.resolve_active_goal(USER, course["course_id"])
    assert goal2.goal_id == "GOAL-C"


def test_course_api_goal_matches_bundle(learner):
    course = _make_course(learner, topic="Transformer")
    learner.set_current_goal(USER, course["course_id"], "GOAL-X")
    learner.upsert_goal(USER, "GOAL-X", course["course_id"], name="X", target="理解原理", priority=9)
    course_row = course_service.get_course(USER, course["course_id"], learner)
    assert course_row["goal"]["goal_id"] == "GOAL-X"
    bundle = learner.build_bundle(USER, course["course_id"])
    assert bundle.active_goal.goal_id == "GOAL-X"


# ---------------------------------------------------------------- 15. apply_event 幂等并发
def test_apply_event_concurrent_idempotent(learner):
    from edu_agent.learner_model.service import LearnerModelService

    errors: list = []

    def worker(i):
        try:
            s = LearnerModelService(db_path=learner._repo._db_path)
            s.apply_event({
                "event_id": "EV-SAME", "event_type": "USER_EXPLICIT_PROFILE_FACT",
                "user_id": USER, "source": "USER_EXPLICIT",
                "payload": {"fact_key": "skill:concurrent", "fact_value": "v"},
            })
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    events = [e for e in learner.repo.list_events(USER) if e["event_id"] == "EV-SAME"]
    assert len(events) == 1


# ---------------------------------------------------------------- 16/17. three stages
def test_three_stages_all_nonempty_extreme():
    si = StudentInput(topic="RAG", level=None, days=5, daily_time="45分钟", goal="g")
    dec = DecompositionResult(
        prerequisite_concepts=[], core_concepts=[], learning_sequence=[], difficulty_points=[],
        stages=_stages(), application_directions=[],
    )
    km = build_knowledge_map(si, dec)
    assert {n.stage_order for n in km.nodes} == {1, 2, 3}
    for order in (1, 2, 3):
        assert any(n.stage_order == order for n in km.nodes)


def test_stage_two_core_fallback_when_missing():
    si = StudentInput(topic="Kafka", level=None, days=7, daily_time="60分钟", goal="g")
    dec = DecompositionResult(
        prerequisite_concepts=["基础"], core_concepts=[], learning_sequence=["基础"],
        difficulty_points=[], stages=_stages(), application_directions=["项目"],
    )
    km = build_knowledge_map(si, dec)
    core = [n for n in km.nodes if n.category == "核心知识"]
    assert len(core) == 1
    assert "核心概念与主线方法" in core[0].title
    assert core[0].stage_order == 2


def test_stage_node_ordering():
    si = StudentInput(topic="Python", level=None, days=14, daily_time="60分钟", goal="g")
    dec = DecompositionResult(
        prerequisite_concepts=["环境安装"], core_concepts=["NumPy"], learning_sequence=["环境", "NumPy"],
        difficulty_points=[], stages=_stages(), application_directions=["数据分析案例"],
    )
    km = build_knowledge_map(si, dec)
    orders = [n.stage_order for n in km.nodes]
    assert orders == sorted(orders)  # 1,1,2,3,3 顺序稳定
    # seq 编号连续且顺序与 stage 一致
    ids = [int(n.id.split("-")[1]) for n in km.nodes]
    assert ids == list(range(1, len(km.nodes) + 1))
    assert km.recommended_path == [n.id for n in km.nodes]


# ---------------------------------------------------------------- 18. plan finalize rollback
def test_plan_finalize_rollback_keeps_old_plan(learner):
    course = _make_course(learner)
    plan1 = generate_plan(USER, course["course_id"], learner=learner)
    assert plan1 is not None
    old_plan_id = plan1["plan_id"]

    # 第二次生成时让 upsert_plan 抛错 → 旧 plan 必须保留
    import edu_agent.learner_model.sqlite_repository as repo_mod

    original = repo_mod.SQLiteLearnerRepository.upsert_plan
    calls = {"n": 0}

    def boom(self, plan):
        calls["n"] += 1
        raise RuntimeError("db boom")  # 第二次 generate 的首次 upsert_plan 即抛错

    repo_mod.SQLiteLearnerRepository.upsert_plan = boom
    try:
        with pytest.raises(RuntimeError):
            generate_plan(USER, course["course_id"], learner=learner)
    finally:
        repo_mod.SQLiteLearnerRepository.upsert_plan = original
    plan_after = learner.repo.get_plan(USER, course["course_id"])
    assert plan_after["plan_id"] == old_plan_id  # 旧 plan 仍在


# ---------------------------------------------------------------- 19/20. DB 约束
def test_one_current_plan_unique_constraint(learner):
    course = _make_course(learner)
    generate_plan(USER, course["course_id"], learner=learner)
    with pytest.raises(Exception) as exc_info:  # IntegrityError
        learner.repo._conn().execute(
            "INSERT INTO study_plans (plan_id, user_id, course_id, title, plan_markdown, created_at, updated_at) "
            "VALUES ('PLAN-EXTRA', ?, ?, 't', 'm', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (USER, course["course_id"]),
        )
        learner.repo._commit()
    assert "UNIQUE" in str(exc_info.value)


def test_progress_check_constraint(learner):
    course = _make_course(learner)
    generate_plan(USER, course["course_id"], learner=learner)
    with pytest.raises(Exception):
        learner.repo._conn().execute(
            "UPDATE study_plans SET progress=1.5 WHERE user_id=? AND course_id=?",
            (USER, course["course_id"]),
        )
        learner.repo._commit()


# ---------------------------------------------------------------- 21. course delete event atomic
def test_course_delete_event_persisted(learner):
    course = _make_course(learner)
    course_service.delete_course(USER, course["course_id"], learner=learner)
    assert learner.repo.get_user_course(USER, course["course_id"]) is None
    events = [e for e in learner.repo.list_events(USER) if e["event_type"] == "COURSE_DELETED"]
    assert len(events) == 1
    assert events[0]["course_id"] == course["course_id"]
