"""AdaptivePolicy 测试：mastery / confidence / prerequisite / misconception / temporal。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.context_selector import select_context  # noqa: E402
from edu_agent.adaptive.policy import make_decision  # noqa: E402
from edu_agent.adaptive.schemas import (  # noqa: E402
    REASON_ACTIVE_MISCONCEPTION,
    REASON_HIGH_REVIEW_RISK,
    REASON_LOW_MASTERY_CONFIDENCE,
    REASON_LOW_PREREQUISITE_MASTERY,
    REASON_LOW_TARGET_MASTERY,
    REASON_TARGET_MASTERED,
)
from edu_agent.adaptive.temporal_resolver import resolve  # noqa: E402
from edu_agent.domain.learning.kc_graph import java_oop_course  # noqa: E402
from edu_agent.integrations.learner_state.mock_provider import MockLearnerStateProvider  # noqa: E402
from edu_agent.integrations.learner_state.schemas import KnowledgeItem  # noqa: E402

COURSE = java_oop_course()


def _context_for(mastery: float, confidence: float, misconceptions=None):
    bundle = MockLearnerStateProvider().get_bundle("STU-001", "JAVA-OOP")
    # 覆盖 POLYMORPHISM 掌握度
    for item in bundle.course_state.knowledge:
        if item.kc_id == "POLYMORPHISM":
            item.mastery = mastery
            item.confidence = confidence
    if misconceptions is not None:
        bundle.course_state.misconceptions = misconceptions
    return select_context(bundle, "topic_tutor", COURSE, target_kc="POLYMORPHISM")


def test_low_mastery_vs_high_mastery_different_policy():
    low = make_decision(_context_for(0.20, 0.80), COURSE, "topic_tutor")
    high = make_decision(_context_for(0.90, 0.80), COURSE, "topic_tutor")
    assert low.depth == "basic"
    assert high.depth == "concise"
    assert REASON_LOW_TARGET_MASTERY in low.reason_codes
    assert REASON_TARGET_MASTERED in high.reason_codes
    assert low != high


def test_confidence_low_changes_policy():
    low_conf = make_decision(_context_for(0.20, 0.10), COURSE, "topic_tutor")
    high_conf = make_decision(_context_for(0.20, 0.95), COURSE, "topic_tutor")
    assert REASON_LOW_MASTERY_CONFIDENCE in low_conf.reason_codes
    assert REASON_LOW_MASTERY_CONFIDENCE not in high_conf.reason_codes
    # 低置信度 → 更多理解检查
    assert "CHECK_UNDERSTANDING" in low_conf.pedagogical_actions


def test_prerequisite_gap_triggers_review():
    # POLYMORPHISM=.24，前置 INHERITANCE=.17 / ENCAPSULATION=.00 均未掌握
    decision = make_decision(_context_for(0.24, 0.78), COURSE, "topic_tutor")
    assert decision.review_prerequisite is True
    assert "INHERITANCE" in decision.prerequisite_topics
    assert "ENCAPSULATION" in decision.prerequisite_topics
    assert "REVIEW_PREREQUISITE" in decision.pedagogical_actions
    assert REASON_LOW_PREREQUISITE_MASTERY in decision.reason_codes


def test_active_misconception_changes_actions():
    from edu_agent.integrations.learner_state.schemas import Misconception

    misconceptions = [
        Misconception(
            misconception_id="MIS-1", kc_id="POLYMORPHISM",
            type="conceptual_confusion", description="混淆静态/动态类型",
            severity=0.78, confidence=0.82, occurrence_count=4, status="active",
        )
    ]
    decision = make_decision(_context_for(0.5, 0.7, misconceptions), COURSE, "topic_tutor")
    assert "CONCEPT_COMPARISON" in decision.pedagogical_actions
    assert "COUNTEREXAMPLE" in decision.pedagogical_actions
    assert REASON_ACTIVE_MISCONCEPTION in decision.reason_codes


def test_temporal_resolver_recency():
    old = KnowledgeItem(
        kc_id="X", mastery=0.85, confidence=0.9,
        last_evidence_at="2025-01-01T00:00:00Z",
    )
    state_old = resolve(old)
    assert state_old.effective_state == "needs_refresh"
    assert state_old.review_risk == "high"

    fresh = KnowledgeItem(
        kc_id="X", mastery=0.85, confidence=0.9,
        last_evidence_at="2026-08-09T00:00:00Z",
    )
    state_fresh = resolve(fresh)
    assert state_fresh.effective_state == "mastered"
    assert state_fresh.review_risk == "low"


def test_temporal_policy_review_risk():
    decision = make_decision(_context_for(0.85, 0.8), COURSE, "topic_tutor")
    # 当前 mock 无 last_evidence_at → recency None → 低风险
    assert REASON_HIGH_REVIEW_RISK not in decision.reason_codes
    # 人为制造高 recency（120 天前的证据）
    bundle = MockLearnerStateProvider().get_bundle("STU-001", "JAVA-OOP")
    for item in bundle.course_state.knowledge:
        if item.kc_id == "POLYMORPHISM":
            item.mastery = 0.85
            item.confidence = 0.8
            item.last_evidence_at = "2026-01-01T00:00:00Z"
    context = select_context(bundle, "topic_tutor", COURSE, target_kc="POLYMORPHISM")
    decision2 = make_decision(context, COURSE, "topic_tutor")
    assert REASON_HIGH_REVIEW_RISK in decision2.reason_codes
    assert decision2.review_or_new == "review"


def test_decision_records_state_version():
    decision = make_decision(_context_for(0.24, 0.78), COURSE, "topic_tutor")
    # mock 未提供 state_version → None（不编造）；有版本时应透传
    assert decision.learner_state_version is None
    from edu_agent.adaptive.schemas import SelectedLearnerContext

    ctx = _context_for(0.24, 0.78)
    ctx.learner_state_version = 37
    decision2 = make_decision(ctx, COURSE, "topic_tutor")
    assert decision2.learner_state_version == 37
