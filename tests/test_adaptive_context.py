"""AdaptiveContextSelector 测试：不同任务类型必须选择不同上下文。

数据来自本地 SQLite Learner Model（seed 后 build_bundle）。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.context_selector import select_context  # noqa: E402
from edu_agent.domain.learning.kc_graph import java_oop_course  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402

USER = "STU-001"
COURSE_ID = "JAVA-OOP"


def _seed_service(tmp_path):
    """seed 本地模型：全课程 KC（来自 domain）+ 一个 active 目标。"""
    service = LearnerModelService(db_path=str(tmp_path / "lm.db"))
    service.ensure_course(USER, COURSE_ID)
    course = java_oop_course()
    for kc in course.components:
        service.repo.upsert_kc(
            {
                "user_id": USER, "course_id": COURSE_ID, "kc_id": kc.kc_id,
                "kc_name": kc.title, "mastery": 0.0, "confidence": None,
                "status": "unknown", "trend": None, "evidence_count": 0,
                "first_evidence_at": None, "last_evidence_at": None,
                "is_estimated": 0, "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
    service.upsert_goal(
        USER, "GOAL-JAVA-001", COURSE_ID,
        name="Java OOP 实训",
        target="完成 OOP 成绩管理系统",
        target_kcs=["ENCAPSULATION", "INHERITANCE", "POLYMORPHISM"],
    )
    return service


def _bundle(tmp_path):
    return _seed_service(tmp_path).build_bundle(USER, COURSE_ID)


def test_study_plan_context_has_goal_and_snapshot(tmp_path):
    bundle = _bundle(tmp_path)
    ctx = select_context(bundle, "study_plan", java_oop_course(), target_kc="POLYMORPHISM")
    assert ctx.task_type == "study_plan"
    assert ctx.goal_name == "Java OOP 实训"
    assert len(ctx.knowledge_snapshot) >= 7  # 全课程掌握度快照


def test_topic_tutor_context_is_narrow(tmp_path):
    bundle = _bundle(tmp_path)
    ctx = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    assert ctx.task_type == "topic_tutor"
    assert ctx.target_kc == "POLYMORPHISM"
    # 只加载目标 KC + 前置链，不加载无关 KC
    snapshot_ids = {item.get("kc_id") for item in ctx.knowledge_snapshot}
    assert snapshot_ids <= {"POLYMORPHISM", "INHERITANCE", "ENCAPSULATION", "CLASS"}
    assert "IO" not in snapshot_ids
    prereq_ids = {item.get("kc_id") for item in ctx.prerequisite_knowledge}
    assert {"INHERITANCE", "ENCAPSULATION"} <= prereq_ids
    assert ctx.misconceptions == []


def test_adaptive_qa_non_learning_question_minimal_context(tmp_path):
    bundle = _bundle(tmp_path)
    ctx = select_context(bundle, "adaptive_qa", java_oop_course(), target_kc=None, query="怎么查日志")
    assert ctx.knowledge_snapshot == []
    assert ctx.misconceptions == []


def test_task_types_select_different_contexts(tmp_path):
    bundle = _bundle(tmp_path)
    plan = select_context(bundle, "study_plan", java_oop_course())
    tutor = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    assert plan.task_type != tutor.task_type
    assert plan.goal_name == tutor.goal_name  # 全局目标共享


def test_multi_course_isolation(tmp_path):
    """Java 的 KC 状态不能出现在 Transformer 课程 bundle 中。"""
    service = _seed_service(tmp_path)
    # 给 Java seed 一些掌握度
    service.repo.upsert_kc(
        {
            "user_id": USER, "course_id": "JAVA-OOP", "kc_id": "POLYMORPHISM",
            "kc_name": "多态", "mastery": 0.9, "confidence": 0.8,
            "status": "mastered", "trend": "improving", "evidence_count": 5,
            "first_evidence_at": "2026-08-01T00:00:00Z", "last_evidence_at": "2026-08-08T00:00:00Z",
            "is_estimated": 0, "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-08T00:00:00Z",
        }
    )
    # Transformer 课程：无任何数据（ensure_course 只建空课程状态）
    service.ensure_course(USER, "TRANSFORMER")
    tf_bundle = service.build_bundle(USER, "TRANSFORMER")
    assert tf_bundle.course_state.knowledge == []
    assert tf_bundle.course_id == "TRANSFORMER"
    # Java 的掌握度没有泄漏到 Transformer
    java_ids = {k.kc_id for k in service.build_bundle(USER, "JAVA-OOP").course_state.knowledge}
    assert "POLYMORPHISM" in java_ids
