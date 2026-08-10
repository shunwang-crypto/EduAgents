"""Dynamic Learner Model V1 正确性收口测试（unknown 语义/事务/版本/幂等/生命周期/多课程/迁移）。"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.context_selector import select_context  # noqa: E402
from edu_agent.adaptive.course_resolver import resolve_course_id, resolve_goal_id  # noqa: E402
from edu_agent.adaptive.policy import make_decision  # noqa: E402
from edu_agent.adaptive.schemas import (  # noqa: E402
    REASON_LOW_TARGET_MASTERY,
    REASON_UNKNOWN_KNOWLEDGE_STATE,
)
from edu_agent.domain.learning.course_builder import (  # noqa: E402
    build_course_from_nodes,
    load_course_from_repo,
    persist_course,
)
from edu_agent.domain.learning.kc_graph import java_oop_course  # noqa: E402
from edu_agent.learner_model.db import connect  # noqa: E402
from edu_agent.learner_model.evidence.extractor import build_event  # noqa: E402
from edu_agent.learner_model.evidence.semantic_classifier import classify  # noqa: E402
from edu_agent.learner_model.evidence.schemas import StructuredEvidence  # noqa: E402
from edu_agent.learner_model.migrations import current_version, migrate  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402
from edu_agent.learner_model.sqlite_repository import SQLiteLearnerRepository  # noqa: E402

USER = "STU-001"
COURSE = "JAVA-OOP"


def _service(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


def _event(etype, user=USER, course=COURSE, kc="POLYMORPHISM", payload=None, session="", event_id=""):
    return build_event(
        event_type=etype, user_id=user, course_id=course,
        kc_id=kc, session_id=session, payload=payload or {}, event_id=event_id,
    )


# ----------------------------------------------------------------------
# A. Unknown 语义
# ----------------------------------------------------------------------
def test_unknown_mastery_is_none(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXPLANATION_REQUESTED", kc="POLYMORPHISM"))
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    assert kc["mastery"] is None
    assert kc["status"] == "unknown"


def test_unknown_ability_score_is_none(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    bundle = service.build_bundle(USER, COURSE)
    assert bundle.course_state.abilities == {}  # 无证据不出现假 0 分


def test_weak_ability_evidence_no_score(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 弱证据（普通行为）不初始化能力分数
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="POLYMORPHISM"))
    abilities = service.repo.list_abilities(USER, COURSE)
    assert abilities == []


# ----------------------------------------------------------------------
# B. Known Zero 保持
# ----------------------------------------------------------------------
def test_known_zero_not_migrated_to_none(tmp_path):
    """已知 0 掌握度（有置信度）不能迁移回 None。"""
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.repo.upsert_kc(
        {"user_id": USER, "course_id": COURSE, "kc_id": "X", "kc_name": "X",
         "mastery": 0.0, "confidence": 0.9, "status": "weak", "trend": None,
         "evidence_count": 3, "first_evidence_at": "2026-08-01T00:00:00Z",
         "last_evidence_at": "2026-08-08T00:00:00Z", "is_estimated": 0,
         "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-08T00:00:00Z"}
    )
    bundle = service.build_bundle(USER, COURSE)
    item = bundle.course_state.get_knowledge("X")
    assert item.mastery == 0.0
    assert item.confidence == 0.9


# ----------------------------------------------------------------------
# C. Adaptive Unknown
# ----------------------------------------------------------------------
def test_adaptive_unknown_not_low_mastery(tmp_path):
    """UNKNOWN KC：不得 LOW_TARGET_MASTERY，必须 UNKNOWN_KNOWLEDGE_STATE。"""
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXPLANATION_REQUESTED", kc="POLYMORPHISM"))
    bundle = service.build_bundle(USER, COURSE)
    ctx = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    decision = make_decision(ctx, java_oop_course(), "topic_tutor")
    assert REASON_UNKNOWN_KNOWLEDGE_STATE in decision.reason_codes
    assert REASON_LOW_TARGET_MASTERY not in decision.reason_codes
    assert decision.depth == "medium"  # 中性首次教学，不武断


# ----------------------------------------------------------------------
# D. Temporal Unknown
# ----------------------------------------------------------------------
def test_temporal_unknown(tmp_path):
    from edu_agent.adaptive.temporal_resolver import resolve
    from edu_agent.learner_model.schemas import KnowledgeItem

    state = resolve(KnowledgeItem(kc_id="X", mastery=None, last_evidence_at="2026-08-01T00:00:00Z"))
    assert state.effective_state == "unknown"
    assert state.raw_mastery is None
    assert state.recency_days is None


# ----------------------------------------------------------------------
# E. KST Unknown prerequisite
# ----------------------------------------------------------------------
def test_kst_unknown_prerequisite_not_auto_passed(tmp_path):
    from edu_agent.domain.learning.kc_graph import reachable_frontier

    course = java_oop_course()
    # ENCAPSULATION UNKNOWN（不在 map）→ INHERITANCE/POLYMORPHISM 不应进入 frontier
    frontier = reachable_frontier(course, {"CLASS": 0.9, "ENCAPSULATION": None})
    assert "INHERITANCE" not in frontier
    assert "POLYMORPHISM" not in frontier
    # 但 ENCAPSULATION 自身（前置 CLASS 已掌握）可以进入
    assert "ENCAPSULATION" in frontier


def test_prerequisite_unknown_reason(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 只给 POLYMORPHISM 一条曝光（UNKNOWN），前置 INHERITANCE/ENCAPSULATION 完全无数据
    service.apply_event(_event("EXPLANATION_REQUESTED", kc="POLYMORPHISM"))
    bundle = service.build_bundle(USER, COURSE)
    ctx = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    decision = make_decision(ctx, java_oop_course(), "topic_tutor")
    from edu_agent.adaptive.schemas import REASON_PREREQUISITE_UNKNOWN

    assert REASON_PREREQUISITE_UNKNOWN in decision.reason_codes


# ----------------------------------------------------------------------
# F. Transaction Rollback
# ----------------------------------------------------------------------
def test_transaction_rollback(tmp_path):
    repo = SQLiteLearnerRepository(str(tmp_path / "lm.db"))
    try:
        with repo.transaction():
            repo.insert_event({
                "event_id": "EV-RB", "schema_version": 1, "event_type": "QUESTION_ASKED",
                "user_id": USER, "course_id": COURSE, "goal_id": "", "kc_id": "",
                "session_id": "", "timestamp": "2026-08-10T00:00:00Z",
                "source": "SYSTEM_OBSERVATION", "evidence_strength": "weak",
                "payload_json": "{}", "created_at": "2026-08-10T00:00:00Z",
            })
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not repo.event_exists("EV-RB")  # 回滚后不残留
    assert repo.count_events(USER, COURSE) == 0


# ----------------------------------------------------------------------
# G. Event Idempotency
# ----------------------------------------------------------------------
def test_event_idempotent(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    event = _event("EXAMPLE_REQUESTED", kc="POLYMORPHISM", event_id="EV-IDEM")
    service.apply_event(event)
    service.apply_event(event)  # 同 event_id 第二次
    pref = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref["evidence_count"] == 1  # 只应用一次
    state = service.repo.get_course_state(USER, COURSE)
    assert state["state_version"] == 2  # ensure_course(1) + 一次应用(2)，没有重复 +


# ----------------------------------------------------------------------
# H. Global/Course 双版本 + 禁止 course_id=""
# ----------------------------------------------------------------------
def test_global_and_course_versions_separate(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    v0_global = service.repo.get_learner(USER)["global_state_version"]
    v0_course = service.repo.get_course_state(USER, COURSE)["state_version"]
    # 全局变更（profile fact）只动 global
    service.set_profile_fact(USER, "python", "会基础")
    assert service.repo.get_learner(USER)["global_state_version"] > v0_global
    assert service.repo.get_course_state(USER, COURSE)["state_version"] == v0_course
    # 课程变更（knowledge）只动 course
    service.apply_event(_event("EXPLANATION_DELIVERED", kc="POLYMORPHISM"))
    assert service.repo.get_course_state(USER, COURSE)["state_version"] > v0_course


def test_global_event_does_not_create_empty_course(tmp_path):
    service = _service(tmp_path)
    # 全局偏好事件 course_id=""：不得创建 (user, "") 课程状态
    service.set_preference(USER, "worked_example", direction="pos")
    assert service.repo.get_course_state(USER, "") is None
    assert service.repo.get_learner(USER)["global_state_version"] >= 1


# ----------------------------------------------------------------------
# I. Change Log before/after
# ----------------------------------------------------------------------
def test_change_log_before_after(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXAMPLE_REQUESTED", kc="POLYMORPHISM"))
    changes = service.get_changes(USER)
    pref_changes = [c for c in changes if "preference" in c.get("entity_type", "")]
    assert pref_changes
    before = json.loads(pref_changes[0]["before_json"] or "null")
    after = json.loads(pref_changes[0]["after_json"] or "null")
    assert before is None or "score" in before  # CREATE 无 before；REINFORCE 有
    assert after and "score" in after


def test_change_log_sensitive_delete_no_content(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "fastapi", "做过 FastAPI 项目")
    service.delete_profile_fact(USER, "fastapi")
    deletes = [c for c in service.get_changes(USER) if c["operation"] == "DELETE"]
    assert deletes
    assert deletes[0]["before_json"] is None
    assert deletes[0]["after_json"] is None


# ----------------------------------------------------------------------
# J. Misconception multi-key
# ----------------------------------------------------------------------
def test_misconception_multi_key(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    event = build_event(
        "SELF_REPORTED_CONFUSION", user_id=USER, course_id=COURSE, kc_id="POLYMORPHISM",
        payload={"misconception_key": "static_vs_dynamic_type", "description_hint": "混淆静态/动态类型"},
    )
    ev1 = StructuredEvidence.from_event(event, entity_type="misconception", entity_key="POLYMORPHISM",
                                        direction="pos", meaningful=True, extra_payload=event.payload)
    event2 = build_event(
        "SELF_REPORTED_CONFUSION", user_id=USER, course_id=COURSE, kc_id="POLYMORPHISM",
        payload={"misconception_key": "reference_vs_object", "description_hint": "混淆引用与对象"},
    )
    ev2 = StructuredEvidence.from_event(event2, entity_type="misconception", entity_key="POLYMORPHISM",
                                        direction="pos", meaningful=True, extra_payload=event2.payload)
    from edu_agent.learner_model.updaters import misconception as mu

    mu.apply_misconception_evidence(service.repo, ev1)
    mu.apply_misconception_evidence(service.repo, ev2)
    misconceptions = service.repo.list_misconceptions(USER, COURSE)
    assert len(misconceptions) == 2
    keys = {m["misconception_key"] for m in misconceptions}
    assert keys == {"static_vs_dynamic_type", "reference_vs_object"}


# ----------------------------------------------------------------------
# K. Preference weakening lifecycle
# ----------------------------------------------------------------------
def test_preference_weakening_lifecycle(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    # 多次请求示例 → worked_example 强化到 active
    for _ in range(15):
        service.apply_event(_event("EXAMPLE_REQUESTED", kc="POLYMORPHISM"))
    pref = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref["status"] == "active"
    # 连续对 worked_example 教学方式给负面反馈 → weakening → inactive
    from edu_agent.learner_model.updaters import preference as pu

    for _ in range(12):
        neg_event = build_event(
            "FEEDBACK_GIVEN", user_id=USER, course_id=COURSE,
            payload={"direction": "negative", "delivery_mode": "worked_example"},
        )
        neg_ev = StructuredEvidence.from_event(
            neg_event, entity_type="preference", entity_key="worked_example",
            direction="neg", meaningful=True, extra_payload=neg_event.payload,
        )
        pu.apply_preference_evidence(service.repo, neg_ev)
    pref3 = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref3["status"] in ("weakening", "inactive")
    # inactive 后明确正向 → reactivate 起点
    service.apply_event(_event("EXAMPLE_REQUESTED", kc="POLYMORPHISM"))
    pref4 = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref4["status"] != "inactive"


# ----------------------------------------------------------------------
# L. Profile Fact False 值
# ----------------------------------------------------------------------
def test_profile_fact_false_value(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "debug_mode", False)
    fact = service.repo.get_profile_fact(USER, "debug_mode")
    assert json.loads(fact["fact_value_json"]) is False  # 不被 or True 吞掉


def test_profile_fact_explicit_correction_resets_confidence(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.set_profile_fact(USER, "programming_level", "advanced")
    service.set_profile_fact(USER, "programming_level", "basic")
    fact = service.repo.get_profile_fact(USER, "programming_level")
    assert json.loads(fact["fact_value_json"]) == "basic"
    assert fact["confidence"] == 0.9  # USER_EXPLICIT 重设，非 max
    assert len(service.repo.list_profile_facts(USER)) == 1  # 不重复追加


# ----------------------------------------------------------------------
# M. Goal multi-user 隔离
# ----------------------------------------------------------------------
def test_goal_multi_user_isolated(tmp_path):
    service = _service(tmp_path)
    service.ensure_course("A", COURSE)
    service.ensure_course("B", COURSE)
    service.upsert_goal("A", "GOAL-001", COURSE, name="A 的目标")
    service.upsert_goal("B", "GOAL-001", COURSE, name="B 的目标")
    assert service.repo.get_goal("A", "GOAL-001")["name"] == "A 的目标"
    assert service.repo.get_goal("B", "GOAL-001")["name"] == "B 的目标"


# ----------------------------------------------------------------------
# N. Memory course isolation
# ----------------------------------------------------------------------
def test_memory_course_isolation(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, "JAVA-OOP")
    service.ensure_course(USER, "TRANSFORMER")
    service.add_memory(USER, "用户做过 Java 成绩管理系统", course_id="JAVA-OOP")
    service.add_memory(USER, "用户用汽车类比理解过多态", course_id="JAVA-OOP")
    tf_effective = service.repo.list_effective_memories(USER, "TRANSFORMER")
    assert tf_effective == []  # Java 记忆不得进入 Transformer 上下文
    java_effective = service.repo.list_effective_memories(USER, "JAVA-OOP")
    assert len(java_effective) == 2
    # Global 记忆两类课程都能看到
    service.add_memory(USER, "用户熟悉 FastAPI", course_id="")
    assert len(service.repo.list_effective_memories(USER, "TRANSFORMER")) == 1


# ----------------------------------------------------------------------
# O. Behavior 30 天过滤 + session 时长
# ----------------------------------------------------------------------
def test_behavior_30d_filter(tmp_path):
    from datetime import datetime, timedelta, timezone

    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    e1 = _event("QUESTION_ASKED", event_id="EV-OLD")
    e1.timestamp = old_ts
    e2 = _event("QUESTION_ASKED", event_id="EV-NEW")
    e2.timestamp = new_ts
    service.apply_event(e1)
    service.apply_event(e2)
    behavior = service.build_bundle(USER, COURSE).course_state.behavior
    assert behavior.activity_count_30d == 1  # 31 天前的被过滤


def test_session_duration_not_fabricated(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("QUESTION_ASKED", kc=""))
    behavior = service.build_bundle(USER, COURSE).course_state.behavior
    assert behavior.average_session_minutes is None  # 无 session 证据不编造 25


def test_session_duration_from_events(tmp_path):
    from datetime import datetime, timedelta, timezone

    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    t0 = datetime.now(timezone.utc)
    e1 = build_event("SESSION_STARTED", user_id=USER, course_id=COURSE,
                     session_id="S1", payload={}, event_id="EV-S1")
    e1.timestamp = t0.isoformat()
    e2 = build_event("SESSION_ENDED", user_id=USER, course_id=COURSE,
                     session_id="S1", payload={}, event_id="EV-S2")
    e2.timestamp = (t0 + timedelta(minutes=20)).isoformat()
    service.apply_event(e1)
    service.apply_event(e2)
    behavior = service.build_bundle(USER, COURSE).course_state.behavior
    assert behavior.average_session_minutes == 20.0


# ----------------------------------------------------------------------
# P. Dynamic course + CourseResolver
# ----------------------------------------------------------------------
def test_course_resolver_stable(tmp_path):
    cid1 = resolve_course_id("Python 数据分析")
    cid2 = resolve_course_id("Python 数据分析")
    assert cid1 == cid2
    assert cid1 != "JAVA-OOP"
    assert resolve_course_id("Java OOP 实训") == "JAVA-OOP"
    assert resolve_course_id("多态") != "JAVA-OOP"  # 不确定匹配 → 自定义课程


def test_goal_id_user_scoped():
    assert resolve_goal_id("A", "X") != resolve_goal_id("B", "X")


# ----------------------------------------------------------------------
# Q. Dynamic course persistence（跨重启）
# ----------------------------------------------------------------------
def test_course_persistence(tmp_path):
    service = _service(tmp_path)
    nodes = [
        {"id": "KC-VAR", "title": "变量", "category": "基础", "summary": "变量声明",
         "prerequisites": [], "difficulty": "easy"},
        {"id": "KC-LOOP", "title": "循环", "category": "基础", "summary": "for/while",
         "prerequisites": ["变量"], "difficulty": "medium"},
    ]
    course = build_course_from_nodes("CUSTOM-python", "Python 入门", nodes)
    persist_course(service.repo, course, topic="python")
    # 新连接（模拟重启）
    service2 = LearnerModelService(db_path=str(tmp_path / "lm.db"))
    restored = load_course_from_repo(service2.repo, "CUSTOM-python")
    assert restored is not None
    assert restored.kc_by_id("KC-LOOP") is not None
    assert restored.prerequisites("KC-LOOP") == ["KC-VAR"]


# ----------------------------------------------------------------------
# R. Semantic classifier 不误判普通提问
# ----------------------------------------------------------------------
def test_semantic_classifier_does_not_misjudge_question(tmp_path):
    from edu_agent.learner_model.schemas import KnowledgeItem  # noqa: F401

    # 普通好问题：不产生 misconception
    event = build_event(
        "EDUCATIONAL_QUESTION_ASKED", user_id=USER, course_id=COURSE,
        kc_id="ATTENTION", payload={"question": "为什么 Attention 要除以 sqrt(dk)？"},
    )
    candidates = classify(event, use_llm=False)
    assert all(c.entity_type != "misconception" for c in candidates)
    # 明确自述混淆：产生 misconception candidate
    event2 = build_event(
        "SELF_REPORTED_CONFUSION", user_id=USER, course_id=COURSE,
        kc_id="POLYMORPHISM", payload={"text": "我一直以为父类引用就是创建了父类对象"},
    )
    candidates2 = classify(event2, use_llm=False)
    assert any(c.entity_type == "misconception" for c in candidates2)


def test_check_understanding_produces_ability_evidence(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    event = build_event(
        "CHECK_UNDERSTANDING_RESPONSE", user_id=USER, course_id=COURSE,
        kc_id="POLYMORPHISM",
        payload={"text": "变量的静态类型在编译期确定，但重写方法的调用由运行时对象决定"},
    )
    changes = service.apply_event(event)
    # 能力证据（medium）应产生 understanding/reasoning
    abilities = service.repo.list_abilities(USER, COURSE)
    types = {a["ability_type"] for a in abilities}
    assert "understanding" in types
    # 解释正确 → misconception 弱化证据（有 candidate 时降 conf）
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    # 强证据（CHECK_UNDERSTANDING + 分类置信）允许保守初始化 mastery（≤0.3），不凭空给高分
    assert kc["mastery"] == 0.3
    assert kc["confidence"] == 0.3


# ----------------------------------------------------------------------
# S. 弱证据不自动涨 mastery（强证据才小幅初始化）
# ----------------------------------------------------------------------
def test_check_understanding_can_init_mastery_small(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    event = build_event(
        "CHECK_UNDERSTANDING_RESPONSE", user_id=USER, course_id=COURSE,
        kc_id="POLYMORPHISM",
        payload={"text": "因为父类引用指向的是子类对象，方法调用由运行时对象决定，所以会调用子类方法"},
    )
    service.apply_event(event)
    kc = service.repo.get_kc(USER, COURSE, "POLYMORPHISM")
    # 强证据（CHECK_UNDERSTANDING + classifier confidence）允许小幅初始化 mastery
    assert kc["mastery"] is not None
    assert kc["mastery"] <= 0.7  # 受上限约束


# ----------------------------------------------------------------------
# T. Migration：fresh + V1→V2
# ----------------------------------------------------------------------
def test_migration_fresh_db(tmp_path):
    conn = connect(str(tmp_path / "fresh.db"))
    v = migrate(conn)
    assert v == 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "learner_evidences" in tables
    assert "adaptive_decisions" in tables
    assert "domain_courses" in tables
    conn.close()


def test_migration_v1_to_v2_unknown_to_null(tmp_path):
    """V1 库（mastery=0 + unknown + 无 confidence）→ V2 迁移为 NULL。"""
    import sqlite3

    db = str(tmp_path / "v1.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE learners (user_id TEXT PRIMARY KEY, display_name TEXT DEFAULT '',
            education_level TEXT DEFAULT '', language TEXT DEFAULT 'zh', background TEXT DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE learner_kc_states (
            user_id TEXT NOT NULL, course_id TEXT NOT NULL, kc_id TEXT NOT NULL,
            kc_name TEXT DEFAULT '', mastery REAL DEFAULT 0.0, confidence REAL,
            status TEXT DEFAULT 'unknown', trend TEXT, evidence_count INTEGER DEFAULT 0,
            first_evidence_at TEXT, last_evidence_at TEXT, is_estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, course_id, kc_id));
        CREATE TABLE learner_abilities (
            user_id TEXT NOT NULL, course_id TEXT NOT NULL, ability_type TEXT NOT NULL,
            score REAL DEFAULT 0.0, confidence REAL, trend TEXT, evidence_count INTEGER DEFAULT 0,
            first_evidence_at TEXT, last_evidence_at TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, course_id, ability_type));
        CREATE TABLE learning_goals (
            goal_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT DEFAULT '',
            name TEXT NOT NULL, target TEXT DEFAULT '', priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active', progress REAL DEFAULT 0.0,
            target_kcs_json TEXT DEFAULT '[]', deadline TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO learner_kc_states VALUES ('STU-001','JAVA-OOP','POLYMORPHISM','多态',0.0,NULL,'unknown',NULL,1,'2026-08-01','2026-08-01',0,'2026-08-01','2026-08-01');
        INSERT INTO learner_kc_states VALUES ('STU-001','JAVA-OOP','EXCEPTION','异常',0.0,0.9,'weak',NULL,3,'2026-08-01','2026-08-01',0,'2026-08-01','2026-08-01');
        INSERT INTO learner_abilities VALUES ('STU-001','JAVA-OOP','understanding',0.0,NULL,NULL,0,NULL,NULL,'2026-08-01');
        """
    )
    conn.commit()
    conn.close()

    conn = connect(db)
    v = migrate(conn)
    assert v == 2
    unknown = conn.execute(
        "SELECT mastery FROM learner_kc_states WHERE kc_id='POLYMORPHISM'"
    ).fetchone()
    known_zero = conn.execute(
        "SELECT mastery FROM learner_kc_states WHERE kc_id='EXCEPTION'"
    ).fetchone()
    ability = conn.execute(
        "SELECT score FROM learner_abilities WHERE ability_type='understanding'"
    ).fetchone()
    assert unknown["mastery"] is None  # unknown → NULL
    assert known_zero["mastery"] == 0.0  # known zero 保留
    assert ability["score"] is None  # 无置信度的 0 → NULL
    # goals 联合主键已重建
    pk = [r["name"] for r in conn.execute("PRAGMA table_info(learning_goals)").fetchall() if r["pk"]]
    assert set(pk) == {"user_id", "goal_id"}
    conn.close()


# ----------------------------------------------------------------------
# U. 幂等 + 事务 + Evidence 落库
# ----------------------------------------------------------------------
def test_evidence_persisted(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    service.apply_event(_event("EXAMPLE_REQUESTED", kc="POLYMORPHISM"))
    evidences = service.repo.list_evidences(USER, COURSE)
    assert any(ev["entity_type"] == "preference" and ev["entity_key"] == "worked_example" for ev in evidences)


def test_reapply_same_evidence_no_double(tmp_path):
    service = _service(tmp_path)
    service.ensure_course(USER, COURSE)
    event = _event("EXAMPLE_REQUESTED", kc="POLYMORPHISM", event_id="EV-X")
    service.apply_event(event)
    n1 = len([ev for ev in service.repo.list_evidences(USER, COURSE) if ev["event_id"] == "EV-X"])
    service.apply_event(event)  # 同 event_id 第二次：幂等，不再新增证据/变更
    n2 = len([ev for ev in service.repo.list_evidences(USER, COURSE) if ev["event_id"] == "EV-X"])
    assert n1 >= 1 and n1 == n2
    pref = service.repo.get_preference(USER, "worked_example", COURSE)
    assert pref["evidence_count"] == 1  # 只强化一次
