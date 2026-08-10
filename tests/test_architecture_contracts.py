"""架构契约测试：无本地 mastery 变更 / 无练习系统 / 个性化差异 / 学习计划自适应。"""

import sys
import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.prompt_builder import build_prompt_context, decision_instructions  # noqa: E402
from edu_agent.adaptive.schemas import FORBIDDEN_ACTIONS, AdaptiveDecision, PED_ACTIONS  # noqa: E402
from edu_agent.adaptive.service import prepare_adaptive_context  # noqa: E402
from edu_agent.integrations.learner_state.mock_provider import MockLearnerStateProvider  # noqa: E402

SRC = PROJECT_ROOT / "src"


def test_no_local_mastery_mutation_in_src():
    """全项目禁止 mastery += / -= 本地变更；只能读取 LearnerState。"""
    forbidden_patterns = (
        "mastery += ", "mastery -= ", "mastery = mastery",
        "p += ", "p -= ", "mastery[", "update_mastery",
    )
    hits = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            if pattern in text and "learner_state" not in str(path):
                hits.append(f"{path}: {pattern}")
    assert not hits, f"发现本地 mastery 变更残留：{hits}"


def test_no_practice_system_in_core_business():
    """核心业务不再有练习/测验生成模块。"""
    forbidden_dirs = ("quiz", "quiz_generation", "practice_designer", "mistake_reflection")
    present = [d for d in forbidden_dirs if (SRC / "edu_agent" / "workflows" / d).exists()]
    assert not present, f"练习相关目录仍存在：{present}"


def test_no_forbidden_pedagogical_actions():
    for action in FORBIDDEN_ACTIONS:
        assert action not in PED_ACTIONS


def test_tutor_personalization_two_states_differ():
    """同一个问题、两个不同 LearnerState → AdaptiveDecision / Prompt 上下文不同。"""
    provider = MockLearnerStateProvider()
    bundle_a = provider.get_bundle("STU-001", "JAVA-OOP")
    bundle_b = provider.get_bundle("STU-001", "JAVA-OOP")
    for item in bundle_a.course_state.knowledge:
        if item.kc_id == "POLYMORPHISM":
            item.mastery = 0.2
    for item in bundle_b.course_state.knowledge:
        if item.kc_id == "POLYMORPHISM":
            item.mastery = 0.95

    _ctx_a, dec_a, prompt_a = prepare_adaptive_context(
        "topic_tutor", target_kc="POLYMORPHISM", bundle=bundle_a
    )
    _ctx_b, dec_b, prompt_b = prepare_adaptive_context(
        "topic_tutor", target_kc="POLYMORPHISM", bundle=bundle_b
    )
    assert dec_a.depth != dec_b.depth
    assert prompt_a["learner_context"] != prompt_b["learner_context"]


def test_study_plan_adaptive_no_heavy_replan_for_mastered():
    """CLASS mastery=.90：study_plan 决策不应把它当作低掌握重点安排。"""
    provider = MockLearnerStateProvider()
    bundle = provider.get_bundle("STU-001", "JAVA-OOP")
    _ctx, decision, _prompt = prepare_adaptive_context("study_plan", bundle=bundle)
    # 目标 KC 应指向未掌握的核心（POLYMORPHISM 链），而非已掌握的 CLASS
    assert decision.next_kc is not None
    # 掌握度高者不会出现在"下一步"首位：CLASS=.90 不应是 next_kc（除非无其他选择）
    if decision.next_kc:
        item = bundle.course_state.get_knowledge(decision.next_kc)
        assert item is None or item.mastery < 0.9


def test_prompt_builder_contains_decision_and_instructions():
    decision = AdaptiveDecision(
        task_type="topic_tutor",
        target_kc="POLYMORPHISM",
        review_prerequisite=True,
        prerequisite_topics=["INHERITANCE", "ENCAPSULATION"],
        pedagogical_actions=["REVIEW_PREREQUISITE", "EXPLAIN"],
        reason_codes=["LOW_PREREQUISITE_MASTERY"],
    )
    from edu_agent.adaptive.schemas import SelectedLearnerContext

    ctx = SelectedLearnerContext(task_type="topic_tutor", target_kc="POLYMORPHISM")
    prompt = build_prompt_context(decision, ctx, user_request="讲一下多态")
    assert "REVIEW_PREREQUISITE" in prompt["adaptive_decision"]
    assert "LOW_PREREQUISITE_MASTERY" in prompt["adaptive_decision"]
    instructions = decision_instructions(decision)
    assert "前置" in instructions
