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
            # SQLite 写锁是暂时性的：慢 I/O 环境下允许重试（幂等性由 INSERT OR IGNORE 保证）
            for attempt in range(3):
                try:
                    s.apply_event({
                        "event_id": "EV-SAME", "event_type": "USER_EXPLICIT_PROFILE_FACT",
                        "user_id": USER, "source": "USER_EXPLICIT",
                        "payload": {"fact_key": "skill:concurrent", "fact_value": "v"},
                    })
                    return
                except Exception as exc:  # noqa: BLE001
                    if "locked" not in str(exc).lower() or attempt == 2:
                        raise
            errors.append("unreachable")
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
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


# ================================================================ P1-2 GET history latest N
# 现有 test_recent_history_returns_latest_n_chronological 只测了 repo.list_recent_messages；
# 这里直接测 GET /chat 实际走的 get_conversation 路径（它此前用 list_messages = 最早 N 条）。

class _FakeNode:
    def __init__(self, **kw):
        self._d = kw

    def model_dump(self):
        return self._d


class _FakeKnowledgeMap:
    def __init__(self, nodes):
        self.nodes = nodes


@pytest.fixture()
def mock_plan_workflow(monkeypatch):
    """确定性假 workflow：捕获 StudentInput 并返回 3 阶段节点（不调真实 LLM）。"""
    captured = {}

    def fake_workflow(student_input, **kwargs):
        captured["student_input"] = student_input
        nodes = [
            _FakeNode(id="KC1", title="概念", summary="s", learning_objective="o",
                      prerequisites=[], stage_id="stage-1", stage_title="基础准备", stage_order=1,
                      difficulty="easy", estimated_minutes=30),
            _FakeNode(id="KC2", title="核心", summary="s", learning_objective="o",
                      prerequisites=["KC1"], stage_id="stage-2", stage_title="核心学习", stage_order=2,
                      difficulty="medium", estimated_minutes=45),
            _FakeNode(id="KC3", title="应用", summary="s", learning_objective="o",
                      prerequisites=["KC2"], stage_id="stage-3", stage_title="综合应用", stage_order=3,
                      difficulty="hard", estimated_minutes=60),
        ]
        return {
            "final_plan": "## 学习计划",
            "knowledge_map": _FakeKnowledgeMap(nodes),
            "analysis": {}, "decomposition": {}, "research": {},
            "evaluated_research": {}, "draft_plan": {}, "validation": {},
            "review": {"review_summary": "ok"},
        }

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        fake_workflow,
    )
    return captured


def test_get_conversation_returns_latest_100_not_earliest(learner):
    course = _make_course(learner)
    svc = ChatService(learner=learner)
    conv = svc.create_conversation(USER, course["course_id"])
    cid = conv["conversation_id"]
    # 写入 120 条消息（created_at 用 6 位零填充，保证字符串排序 == 数值排序）
    for i in range(1, 121):
        learner.repo.insert_message({
            "message_id": f"MSG-{i:03d}", "conversation_id": cid,
            "role": "user" if i % 2 else "assistant", "content": f"消息{i}",
            "created_at": f"2026-08-12T{i:06d}Z", "metadata_json": "{}",
        })
    res = svc.get_conversation(USER, course_id=course["course_id"])
    msgs = res["messages"]
    assert len(msgs) == 100
    contents = [m["content"] for m in msgs]
    # 最新 100 条 = 消息21..消息120，按 chronological（旧→新）
    assert contents[0] == "消息21"
    assert contents[-1] == "消息120"
    assert "消息1" not in contents  # 最早 20 条被截断
    # chronological 顺序（created_at 升序）
    times = [m["created_at"] for m in msgs]
    assert times == sorted(times)


# ================================================================ P1-3 rename 不改变语义主题
def test_rename_does_not_change_plan_semantic_topic(learner, mock_plan_workflow):
    course = _make_course(learner, topic="Python 数据分析")
    course_service.rename_course(USER, course["course_id"], "30天冲刺课", learner=learner)
    plan = generate_plan(USER, course["course_id"], learner=learner)
    # Plan 语义主题必须用稳定的 course.topic（不是 display_name）
    assert mock_plan_workflow["student_input"].topic == "Python 数据分析"
    # UI 标题仍用 display_name；GET course 返回 rename 后的 display_name
    assert course_service.get_course(USER, course["course_id"], learner)["display_name"] == "30天冲刺课"
    assert plan["title"] == "30天冲刺课 学习计划"


def test_empty_topic_never_leaks_internal_course_id(learner, mock_plan_workflow):
    """退化场景：topic 为空串时，语义主题必须回落 display_name，
    绝不能把内部 course_id（CUSTOM-xxx）或空串当作 Plan 主题（P1-3 + P2-2）。"""
    course = _make_course(learner, topic="Python 数据分析")
    cid = course["course_id"]
    # 人为把 topic 置空（模拟脏数据 / 未来写入路径遗漏）
    learner.repo._conn().execute(
        "UPDATE user_courses SET topic='' WHERE user_id=? AND course_id=?", (USER, cid)
    )
    learner.repo._commit()
    generate_plan(USER, cid, learner=learner)
    used = mock_plan_workflow["student_input"].topic
    assert used == "Python 数据分析"  # 回落 display_name
    assert used != ""
    assert not used.startswith("CUSTOM-")
    assert cid not in used


# ================================================================ P1-4 删除课程清除 course-scoped background
def test_delete_course_removes_background_fact(learner, mock_plan_workflow):
    course = _make_course(learner, topic="SQL")
    cid = course["course_id"]
    # 全局技能（删除课程前写入，必须保留）
    learner.set_profile_fact(USER, "skill:python", "Python")
    # 生成计划时写入当前基础 → background:{course_id}
    generate_plan(USER, cid, learner=learner, optional_background="会 Python 但不会 SQL")
    fact = learner.repo.get_profile_fact(USER, f"background:{cid}")
    assert fact is not None
    assert "会 Python 但不会 SQL" in str(fact.get("fact_value_json"))
    # 删除课程 → background fact 必须被清除，且全局技能不受影响
    course_service.delete_course(USER, cid, learner=learner)
    assert learner.repo.get_profile_fact(USER, f"background:{cid}") is None
    assert learner.repo.get_profile_fact(USER, "skill:python") is not None
    # 重新创建相同 topic（course_id 确定性复用，故与 cid 相同），旧 background 不复活；
    # 注意：不依赖「ID 必须改变」，只验证旧背景事实不残留、重建且不带 background 时不写入新背景。
    course2 = _make_course(learner, topic="SQL")
    generate_plan(USER, course2["course_id"], learner=learner)  # 不设 background
    assert learner.repo.get_profile_fact(USER, f"background:{cid}") is None
    assert learner.repo.get_profile_fact(USER, f"background:{course2['course_id']}") is None


# ================================================================ P2-1 降级计划不泄漏内部异常（final_plan + knowledge_map 节点）
def test_fallback_plan_no_exception_leak(monkeypatch):
    import edu_agent.workflows.study_plan.workflow as wf
    from edu_agent.config.settings import get_settings
    from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow

    # 强制 offline：清空所有外部 AI / search provider 配置，
    # 让 analyzer/decomposer 在无 provider 时立即走确定性降级，
    # 而非联网真实模型（也不产生费用）。planner 仍被强制失败以验证降级不泄漏异常。
    for key in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "XINGCHEN_API_KEY", "XINGCHEN_BASE_URL", "XINGCHEN_MODEL",
        "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_BASE_URL", "OPENCODE_ZEN_MODEL",
        "TAVILY_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()

    def boom(*a, **k):
        raise RuntimeError("LLMConfigurationError: provider unavailable")

    # 让 planner 失败 → 触发 draft 降级（其他 agent 无 provider 也会各自降级）
    monkeypatch.setattr(wf, "planner_agent", boom)
    si = StudentInput(topic="Python 数据分析", level=None, days=14,
                      daily_time="60分钟", goal="学会数据分析")
    result = run_study_plan_workflow(si)
    plan = result["final_plan"]
    # 内部异常文本不得进入用户可见计划内容
    for leak in ("LLMConfigurationError", "provider unavailable", "原因：",
                 "Agent 暂时不可用", "Traceback", "Exception", "降级生成"):
        assert leak not in plan, f"fallback plan leaked into final_plan: {leak}"
    # 同样不得进入 knowledge_map 的任何节点（标题/摘要/目标），否则会被前端渲染成学习步骤
    km = result.get("knowledge_map")
    assert km is not None, "workflow must return a knowledge_map"
    for node in km.nodes:
        blob = " ".join(str(x) for x in (
            getattr(node, "title", ""), getattr(node, "summary", ""),
            getattr(node, "learning_objective", ""), getattr(node, "difficulty", ""),
        ))
        for leak in ("LLMConfigurationError", "provider unavailable", "原因：",
                     "Agent 暂时不可用", "Traceback", "Exception", "降级生成"):
            assert leak not in blob, f"fallback plan leaked into knowledge_map node: {leak}"
    # 仍保持三阶段结构
    assert "阶段安排" in plan


# ================================================================ P1-2 降级分解本身不把异常写进内容字段
def test_fallback_decomposition_no_exception_leak_in_nodes(monkeypatch):
    """直接触发 agents._fallback_decomposition（带真实 exception reason），
    验证降级结果 application_directions 与经 build_knowledge_map 生成的 Stage-3 节点都不含异常文本。"""
    from edu_agent.workflows.study_plan import agents
    from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map
    from edu_agent.workflows.study_plan.schemas import AnalysisResult

    def boom(*a, **k):
        raise RuntimeError("LLMConfigurationError: provider unavailable")

    # 强制 decomposer 的真实 LLM 调用失败 → 触达 _fallback_decomposition(student_input, analysis, exc)
    monkeypatch.setattr(agents, "invoke_structured_output", boom)
    si = StudentInput(topic="Python 数据分析", level=None, days=14,
                      daily_time="60分钟", goal="学会数据分析")
    analysis = AnalysisResult(
        topic="Python 数据分析", level_summary="", goal_summary="",
        prerequisites=[], need_web_search=False, search_queries=[],
    )
    dec = agents.decomposer_agent(si, analysis)
    for leak in ("LLMConfigurationError", "provider unavailable", "原因：",
                 "Agent 暂时不可用", "Traceback", "Exception", "降级生成"):
        joined = " ".join(dec.application_directions)
        assert leak not in joined, f"fallback decomposition leaked into application_directions: {leak}"
    # 经 build_knowledge_map 转换后，Stage-3 节点也不得泄漏
    km = build_knowledge_map(student_input=si, decomposition=dec)
    for node in km.nodes:
        blob = " ".join(str(x) for x in (
            getattr(node, "title", ""), getattr(node, "summary", ""),
            getattr(node, "learning_objective", ""), getattr(node, "difficulty", ""),
        ))
        for leak in ("LLMConfigurationError", "provider unavailable", "原因：",
                     "Agent 暂时不可用", "Traceback", "Exception", "降级生成"):
            assert leak not in blob, f"fallback plan leaked into knowledge_map node: {leak}"


# ================================================================ P1-1 生成期间删除/改名 → 不复活/不覆盖
class _P1FakeNode:
    def __init__(self, **kw):
        self._d = kw

    def model_dump(self):
        return self._d


class _P1FakeKnowledgeMap:
    def __init__(self, nodes):
        self.nodes = nodes


def _p1_fake_workflow(nodes):
    def _wf(student_input, **kwargs):
        return {
            "final_plan": "## 学习计划",
            "knowledge_map": _P1FakeKnowledgeMap(nodes),
            "analysis": {}, "decomposition": {}, "research": {},
            "evaluated_research": {}, "draft_plan": {}, "validation": {},
            "review": {"review_summary": "ok"},
        }
    return _wf


def test_generate_plan_deleted_during_workflow_discards_result(learner, monkeypatch):
    """生成计划期间课程被删除 → 必须抛出 KeyError 丢弃陈旧结果，绝不复活已删课程。"""
    course = _make_course(learner, topic="SQL")
    cid = course["course_id"]
    nodes = [_P1FakeNode(id="KC1", title="概念", summary="s", learning_objective="o",
                         prerequisites=[], stage_id="stage-1", stage_title="基础准备", stage_order=1,
                         difficulty="easy", estimated_minutes=30)]

    def fake_workflow_delete_midway(student_input, **kwargs):
        # 模拟「LLM 很慢期间」用户删除了课程
        course_service.delete_course(USER, cid, learner=learner)
        return _p1_fake_workflow(nodes)(student_input, **kwargs)

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        fake_workflow_delete_midway,
    )
    # course 在 finalize 前已被删 → get_user_course 返回 None → 抛 KeyError（结果被丢弃）
    with pytest.raises(KeyError):
        generate_plan(USER, cid, learner=learner)
    # 课程确实保持删除状态（无残留 plan / course 行）
    assert learner.repo.get_user_course(USER, cid) is None
    assert learner.repo.get_plan(USER, cid) is None


def test_generate_plan_renamed_during_workflow_uses_fresh_name(learner, monkeypatch):
    """生成计划期间课程被改名 → finalize 必须用 fresh 新名，不能拿开头捕获的旧名覆盖。"""
    course = _make_course(learner, topic="Python 数据分析")
    cid = course["course_id"]
    nodes = [_P1FakeNode(id="KC1", title="概念", summary="s", learning_objective="o",
                         prerequisites=[], stage_id="stage-1", stage_title="基础准备", stage_order=1,
                         difficulty="easy", estimated_minutes=30)]

    def fake_workflow_rename_midway(student_input, **kwargs):
        course_service.rename_course(USER, cid, "Py 数据科学课", learner=learner)
        return _p1_fake_workflow(nodes)(student_input, **kwargs)

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        fake_workflow_rename_midway,
    )
    plan = generate_plan(USER, cid, learner=learner)
    # title 必须用改名后的 fresh 名，而非开头捕获的旧 display_name
    assert "Py 数据科学课" in plan["title"]
    assert "Python 数据分析" not in plan["title"]
    # 课程行本身也应为新名（upsert 用了 fresh_course_row）
    assert learner.repo.get_user_course(USER, cid)["display_name"] == "Py 数据科学课"


# ================================================================ P2-1 background 不泄漏内部 course id
def test_humanize_background_does_not_leak_course_id():
    out = humanize_profile_fact("background:CUSTOM-sql-2064cb64", '"会 Python，不熟悉 pandas"')
    assert out == "课程背景：会 Python，不熟悉 pandas"
    assert "CUSTOM-" not in out
    # 无文本时也不暴露 id
    assert humanize_profile_fact("background:CUSTOM-x", None) == "课程背景"
