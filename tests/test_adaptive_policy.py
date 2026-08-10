"""AdaptivePolicy 测试：mastery / confidence / prerequisite / misconception / temporal。

数据来源：本地 SQLite Learner Model（LearnerModelService seed 后 build_bundle），
验证「本地画像 → ContextSelector → Policy」完整链路。
"""

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
from edu_agent.learner_model.schemas import KnowledgeItem  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402

COURSE = java_oop_course()
USER = "STU-001"
COURSE_ID = "JAVA-OOP"


def _seed_service(tmp_path, poly_mastery=0.24, poly_confidence=0.78,
                  poly_last_evidence=None, misconceptions=None):
    """用本地 SQLite 模型 seed Java OOP 种子状态，返回 service。"""
    service = LearnerModelService(db_path=str(tmp_path / "lm.db"))
    service.ensure_course(USER, COURSE_ID)
    base = {
        "ENCAPSULATION": ("封装", 0.0),
        "INHERITANCE": ("继承", 0.17),
        "POLYMORPHISM": ("多态", poly_mastery),
        "COLLECTION": ("集合", 0.0),
    }
    for kc_id, (name, mastery) in base.items():
        confidence = poly_confidence if kc_id == "POLYMORPHISM" else None
        service.repo.upsert_kc(
            {
                "user_id": USER, "course_id": COURSE_ID, "kc_id": kc_id,
                "kc_name": name, "mastery": mastery, "confidence": confidence,
                "status": "weak" if mastery < 0.3 else "learning",
                "trend": None, "evidence_count": 1,
                "first_evidence_at": poly_last_evidence, "last_evidence_at": poly_last_evidence,
                "is_estimated": 0, "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
    if misconceptions:
        for m in misconceptions:
            service.repo.upsert_misconception(m)
    return service


def _context_for(tmp_path, mastery=0.24, confidence=0.78, misconceptions=None,
                 last_evidence=None):
    service = _seed_service(tmp_path, mastery, confidence, last_evidence, misconceptions)
    bundle = service.build_bundle(USER, COURSE_ID)
    return select_context(bundle, "topic_tutor", COURSE, target_kc="POLYMORPHISM")


def test_low_mastery_vs_high_mastery_different_policy(tmp_path):
    low = make_decision(_context_for(tmp_path, 0.20, 0.80), COURSE, "topic_tutor")
    high = make_decision(_context_for(tmp_path, 0.90, 0.80), COURSE, "topic_tutor")
    assert low.depth == "basic"
    assert high.depth == "concise"
    assert REASON_LOW_TARGET_MASTERY in low.reason_codes
    assert REASON_TARGET_MASTERED in high.reason_codes
    assert low != high


def test_confidence_low_changes_policy(tmp_path):
    low_conf = make_decision(_context_for(tmp_path, 0.20, 0.10), COURSE, "topic_tutor")
    high_conf = make_decision(_context_for(tmp_path, 0.20, 0.95), COURSE, "topic_tutor")
    assert REASON_LOW_MASTERY_CONFIDENCE in low_conf.reason_codes
    assert REASON_LOW_MASTERY_CONFIDENCE not in high_conf.reason_codes
    assert "CHECK_UNDERSTANDING" in low_conf.pedagogical_actions


def test_prerequisite_gap_triggers_review(tmp_path):
    decision = make_decision(_context_for(tmp_path, 0.24, 0.78), COURSE, "topic_tutor")
    assert decision.review_prerequisite is True
    assert "INHERITANCE" in decision.prerequisite_topics
    assert "ENCAPSULATION" in decision.prerequisite_topics
    assert "REVIEW_PREREQUISITE" in decision.pedagogical_actions
    assert REASON_LOW_PREREQUISITE_MASTERY in decision.reason_codes


def test_active_misconception_changes_actions(tmp_path):
    misconceptions = [
        {
            "misconception_id": "MIS-1", "user_id": USER, "course_id": COURSE_ID,
            "kc_id": "POLYMORPHISM", "type": "conceptual_confusion",
            "description": "混淆静态/动态类型", "severity": 0.78, "confidence": 0.82,
            "occurrence_count": 4, "status": "active",
            "first_seen_at": "2026-08-01T00:00:00Z", "last_seen_at": "2026-08-08T00:00:00Z",
            "resolved_at": None, "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-08T00:00:00Z",
        }
    ]
    decision = make_decision(_context_for(tmp_path, 0.5, 0.7, misconceptions), COURSE, "topic_tutor")
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


def test_temporal_policy_review_risk(tmp_path):
    # 无 last_evidence → recency None → 低风险
    decision = make_decision(_context_for(tmp_path, 0.85, 0.8), COURSE, "topic_tutor")
    assert REASON_HIGH_REVIEW_RISK not in decision.reason_codes
    # 人为制造高 recency（120 天前的证据）
    decision2 = make_decision(
        _context_for(tmp_path, 0.85, 0.8, last_evidence="2026-01-01T00:00:00Z"),
        COURSE, "topic_tutor",
    )
    assert REASON_HIGH_REVIEW_RISK in decision2.reason_codes
    assert decision2.review_or_new == "review"


def test_decision_records_state_version(tmp_path):
    decision = make_decision(_context_for(tmp_path, 0.24, 0.78), COURSE, "topic_tutor")
    assert decision.learner_state_version is not None
