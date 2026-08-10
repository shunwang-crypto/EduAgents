"""本地 Dynamic Learner Model 测试：SQLite 仓库 / 事件闭环 / 生命周期 / 保守更新。"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.learner_model.db import get_connection  # noqa: E402
from edu_agent.learner_model.evidence.extractor import build_event  # noqa: E402
from edu_agent.learner_model.evidence.schemas import StructuredEvidence  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402
from edu_agent.learner_model.sqlite_repository import SQLiteLearnerRepository  # noqa: E402
from edu_agent.learner_model.updaters import misconception as misconception_updater  # noqa: E402

USER = "STU-001"
COURSE = "JAVA-OOP"


def _service(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


def _event(etype, user=USER, course=COURSE, kc="POLYMORPHISM", payload=None, session=""):
    return build_event(
        event_type=etype, user_id=user, course_id=course,
        kc_id=kc, session_id=session, payload=payload or {},
    )


# ----------------------------------------------------------------------
# Repository 基础
# ----------------------------------------------------------------------
def test_repo_crud_and_multi_user(tmp_path):
    repo = SQLiteLearnerRepository(str(tmp_path / "lm.db"))
    repo.ensure_learner("A")
    repo.ensure_learner("B")
    assert repo.get_learner("A")["user_id"] == "A"
    assert repo.get_learner("C") is None
    # 同 key 事实只保留一条
    repo.upsert_profile_fact(
        {"fact_id": "F1", "user_id": "A", "category": "background", "fact_key": "python",
         "fact_value_json": '"会基础语法"', "confidence": 0.9, "source": "USER_EXPLICIT",
         "status": "active", "first_observed_at": "t", "last_confirmed_at": "t",
         "updated_at": "t", "expires_at": None}
    )
    repo.upsert_profile_fact(
        {"fact_id": "F2", "user_id": "A", "category": "background", "fact_key": "python",
         "fact_value_json": '"会 FastAPI"', "confidence": 0.9, "source": "USER_EXPLICIT",
         "status": "active", "first_observed_at": "t", "last_confirmed_at": "t",
         "updated_at": "t", "expires_at": None}
    )
    facts = repo.list_profile_facts("A")
    assert len(facts) == 1
    assert facts[0]["fact_value_json"] == '"会 FastAPI"'
    assert repo.list_profile_facts("B") == []


def test_repo_events_append_only(tmp_path):
    repo = SQLiteLearnerRepository(str(tmp_path / "lm.db"))
    base = {
        "schema_version": 1, "event_type": "QUESTION_ASKED",
        "user_id": "A", "course_id": "JAVA-OOP", "goal_id": "", "kc_id": "",
        "session_id": "s1", "timestamp": "2026-08-10T00:00:00Z",
        "source": "SYSTEM_OBSERVATION", "evidence_strength": "weak",
        "payload_json": "{}", "created_at": "2026-08-10T00:00:00Z",
    }
    repo.insert_event({**base, "event_id": "EV-1"})
    repo.insert_event({**base, "event_id": "EV-2"})
    # append-only：两条不同事件都在，历史不覆盖
    assert repo.count_events("A", "JAVA-OOP") == 2
    assert len(repo.list_events("A", "JAVA-OOP")) == 2


# ----------------------------------------------------------------------
# 弱证据不能大幅改变 mastery
# ----------------------------------------------------------------------
def test_weak_evidence_does_not_jump_mastery(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 用户说"懂了"：弱证据，mastery 必须保持 0
    service.apply_event(_event("SELF_REPORTED_UNDERSTANDING", kc="POLYMORPHISM"))
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    assert kc["mastery"] == 0.0
    assert kc["evidence_count"] >= 1
    assert kc["last_evidence_at"] is not None


def test_explanation_delivered_only_updates_recency(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="POLYMORPHISM"))
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    assert kc["mastery"] == 0.0
    assert kc["confidence"] is None  # 曝光不编造置信度


def test_confusion_signal_keeps_mastery(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("SELF_REPORTED_CONFUSION", kc="POLYMORPHISM"))
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    assert kc["mastery"] == 0.0  # 不粗暴 -0.2


# ----------------------------------------------------------------------
# Preference 生命周期
# ----------------------------------------------------------------------
def test_preference_reinforce_and_weaken(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    for _ in range(6):
        service.apply_event(_event("EXAMPLE_REQUESTED", kc="POLYMORPHISM"))
    # EXAMPLE_REQUESTED 是课程内行为 → 课程级偏好
    pref = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref["score"] > 0.55
    assert pref["evidence_count"] == 6
    # 用户明确说不要案例 → 跨课程显式设置，课程级偏好应被覆盖/弱化
    service.set_preference(USER, "worked_example", direction="neg")
    bundle = service.build_bundle(USER, COURSE)
    pref_effective = bundle.global_state.preferences.mode_effectiveness["worked_example"]
    assert pref_effective.score < 0.55
    assert pref_effective.confidence >= 0.8  # USER_EXPLICIT 高置信


def test_user_explicit_override_beats_inference(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 弱推断：analogy 偏好涨上去（课程级）
    for _ in range(5):
        service.apply_event(_event("ANALOGY_REQUESTED"))
    assert service.repo.get_preference(USER, "analogy", COURSE)["score"] > 0.5
    # 用户明确说不喜欢类比（跨课程显式声明）
    service.set_preference(USER, "analogy", direction="neg")
    pref = service.repo.get_preference(USER, "analogy")
    assert pref["score"] <= 0.5
    assert pref["confidence"] >= 0.8
    # bundle 中有效偏好（跨课程显式）压过课程级弱推断
    effective = service.build_bundle(USER, COURSE).global_state.preferences.mode_effectiveness["analogy"]
    assert effective.score <= 0.5


# ----------------------------------------------------------------------
# Misconception 生命周期
# ----------------------------------------------------------------------
def _mis_evidence(tmp_path, direction, kc="POLYMORPHISM"):
    event = build_event(
        event_type="SELF_REPORTED_CONFUSION" if direction == "pos" else "SELF_REPORTED_UNDERSTANDING",
        user_id=USER, course_id=COURSE, kc_id=kc,
        payload={"description_hint": "混淆静态/动态类型"},
    )
    # 用 medium 强度模拟「多次连续出现的明确困惑」（弱证据只停留在 candidate）
    event.evidence_strength = "medium"
    return StructuredEvidence.from_event(
        event, entity_type="misconception", entity_key=kc,
        direction=direction, meaningful=True,
    )


def test_misconception_full_lifecycle(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 多次错误 → candidate → active
    statuses = []
    for _ in range(4):
        result = misconception_updater.apply_misconception_evidence(service.repo, _mis_evidence(tmp_path, "pos"))
        statuses.append(result["operation"])
    assert "CREATE" in statuses
    active = service.repo.list_misconceptions(USER, COURSE)
    assert active and active[0]["status"] == "active"
    assert active[0]["occurrence_count"] >= 4
    # 多次正确 → resolving → resolved
    for _ in range(8):
        misconception_updater.apply_misconception_evidence(service.repo, _mis_evidence(tmp_path, "neg"))
    m = service.repo.list_misconceptions(USER, COURSE)[0]
    assert m["status"] == "resolved"
    assert m["resolved_at"] is not None
    # resolved 后不再出现在 bundle（adaptive 不消费已解决误解）
    bundle = service.build_bundle(USER, COURSE)
    assert all(x.status != "resolved" for x in bundle.course_state.misconceptions)
    # 重新出现 → REACTIVATE
    misconception_updater.apply_misconception_evidence(service.repo, _mis_evidence(tmp_path, "pos"))
    m2 = service.repo.list_misconceptions(USER, COURSE)[0]
    assert m2["status"] == "active"


# ----------------------------------------------------------------------
# Profile Fact：UPDATE 不重复追加 / 用户删除
# ----------------------------------------------------------------------
def test_profile_fact_update_not_duplicate(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "python", "会基础语法")
    service.set_profile_fact(USER, "python", "会 FastAPI 项目")
    facts = service.repo.list_profile_facts(USER)
    assert len(facts) == 1
    assert json.loads(facts[0]["fact_value_json"]) == "会 FastAPI 项目"


def test_delete_fact_leaves_no_copy(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "fastapi", "做过 FastAPI 成绩管理系统")
    result = service.delete_profile_fact(USER, "fastapi")
    assert result["operation"] == "DELETE"
    assert service.repo.list_profile_facts(USER) == []
    # change log 最小审计：不保存被删内容全文
    changes = service.get_changes(USER)
    delete_changes = [c for c in changes if c["operation"] == "DELETE"]
    assert delete_changes
    assert delete_changes[0]["after_json"] is None
    assert delete_changes[0]["before_json"] is None


def test_delete_memory(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.add_memory(USER, "用户做过 Java 成绩管理系统")
    memories = service.repo.list_memories(USER)
    assert len(memories) == 1
    service.delete_memory(USER, memories[0]["memory_id"])
    assert service.repo.list_memories(USER) == []


# ----------------------------------------------------------------------
# Ability 慢更新
# ----------------------------------------------------------------------
def test_ability_slow_update(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("SELF_REPORTED_UNDERSTANDING", kc="POLYMORPHISM"))
    abilities = service.build_bundle(USER, COURSE).course_state.abilities
    # 弱证据（weight≈0.03）不应制造精确能力分
    assert not abilities or all(a.confidence is None or a.confidence < 0.5 for a in abilities.values())


# ----------------------------------------------------------------------
# Multi-course 隔离
# ----------------------------------------------------------------------
def test_multi_course_isolation_via_events(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="POLYMORPHISM"))
    service.ensure_course(USER, "TRANSFORMER")
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="ATTENTION", course="TRANSFORMER"))
    java_kcs = {k.kc_id for k in service.build_bundle(USER, COURSE).course_state.knowledge}
    tf_kcs = {k.kc_id for k in service.build_bundle(USER, "TRANSFORMER").course_state.knowledge}
    assert "POLYMORPHISM" in java_kcs
    assert "ATTENTION" in tf_kcs
    assert "POLYMORPHISM" not in tf_kcs
    assert "ATTENTION" not in java_kcs


# ----------------------------------------------------------------------
# 闭环：Event → 画像 → AdaptiveDecision
# ----------------------------------------------------------------------
def test_closed_loop_event_to_decision(tmp_path):
    from edu_agent.adaptive.context_selector import select_context
    from edu_agent.adaptive.policy import make_decision
    from edu_agent.domain.learning.kc_graph import java_oop_course

    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    course = java_oop_course()
    # 用户多次困惑 → misconception 出现 → 决策必须改变
    for _ in range(4):
        service.apply_event(_event("SELF_REPORTED_CONFUSION", kc="POLYMORPHISM"))
    bundle1 = service.build_bundle(USER, COURSE)
    ctx1 = select_context(bundle1, "topic_tutor", course, target_kc="POLYMORPHISM")
    dec1 = make_decision(ctx1, course, "topic_tutor")
    assert "CHECK_UNDERSTANDING" in dec1.pedagogical_actions or dec1.depth == "basic"
    # 状态版本随事件递增
    assert bundle1.course_state.state_version and bundle1.course_state.state_version >= 1


# ----------------------------------------------------------------------
# Goal 生命周期
# ----------------------------------------------------------------------
def test_goal_lifecycle(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.upsert_goal(USER, "GOAL-1", COURSE, name="Java OOP 实训")
    service.update_goal_progress("GOAL-1", 1.0)
    goal = service.repo.get_goal("GOAL-1")
    assert goal["status"] == "completed"
    assert goal["progress"] == 1.0


# ----------------------------------------------------------------------
# 变化记录
# ----------------------------------------------------------------------
def test_change_log_records_operations(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "java", "会基础语法")
    service.set_preference(USER, "worked_example", direction="pos")
    changes = service.get_changes(USER)
    ops = {c["operation"] for c in changes}
    assert "CREATE" in ops
    # 事件更新也会写变化（knowledge exposure）
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="POLYMORPHISM"))
    changes2 = service.get_changes(USER)
    assert len(changes2) > len(changes)
