"""AdaptiveContextSelector 测试：不同任务类型必须选择不同上下文。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.context_selector import select_context  # noqa: E402
from edu_agent.domain.learning.kc_graph import java_oop_course  # noqa: E402
from edu_agent.integrations.learner_state.mock_provider import MockLearnerStateProvider  # noqa: E402


def _bundle():
    return MockLearnerStateProvider().get_bundle("STU-001", "JAVA-OOP")


def test_study_plan_context_has_goal_and_snapshot():
    bundle = _bundle()
    ctx = select_context(bundle, "study_plan", java_oop_course(), target_kc="POLYMORPHISM")
    assert ctx.task_type == "study_plan"
    assert ctx.goal_name == "Java OOP 实训"
    assert len(ctx.knowledge_snapshot) >= 7  # 全课程掌握度快照


def test_topic_tutor_context_is_narrow():
    bundle = _bundle()
    ctx = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    assert ctx.task_type == "topic_tutor"
    assert ctx.target_kc == "POLYMORPHISM"
    # 只加载目标 KC + 前置，不加载无关课程
    snapshot_ids = {item.get("kc_id") for item in ctx.knowledge_snapshot}
    assert snapshot_ids <= {"POLYMORPHISM", "INHERITANCE", "ENCAPSULATION", "CLASS"}
    assert "IO" not in snapshot_ids
    # 有前置（传递链：继承+封装）；mock 不编造误解（合作伙伴未提供 → 空）
    prereq_ids = {item.get("kc_id") for item in ctx.prerequisite_knowledge}
    assert {"INHERITANCE", "ENCAPSULATION"} <= prereq_ids
    assert ctx.misconceptions == []


def test_adaptive_qa_non_learning_question_minimal_context():
    bundle = _bundle()
    ctx = select_context(bundle, "adaptive_qa", java_oop_course(), target_kc=None, query="怎么查日志")
    assert ctx.knowledge_snapshot == []
    assert ctx.misconceptions == []


def test_task_types_select_different_contexts():
    bundle = _bundle()
    plan = select_context(bundle, "study_plan", java_oop_course())
    tutor = select_context(bundle, "topic_tutor", java_oop_course(), target_kc="POLYMORPHISM")
    assert plan.task_type != tutor.task_type
    assert plan.goal_name == tutor.goal_name  # 全局目标共享
