"""LearnerStateAdapter 测试：合作伙伴原始 JSON → 内部模型。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.integrations.learner_state.adapter import (  # noqa: E402
    parse_course_state,
    parse_global_state,
    make_empty_course_state,
)


PARTNER_COURSE_RAW = {
    "schema_version": 1,
    "user_id": "STU-001",
    "course_id": "JAVA-OOP",
    "progress": 0.31,
    "knowledge": [
        {"kc_id": "POLYMORPHISM", "name": "多态", "mastery": 0.24, "confidence": 0.78,
         "status": "weak", "trend": "improving", "evidence_count": 8},
        {"kc_id": "CLASS", "name": "类", "mastery": 0.90, "confidence": 0.92},
    ],
    "abilities": {
        "understanding": {"score": 0.30, "confidence": 0.72, "trend": "stable", "evidence_count": 12},
        "application": 0.31,
    },
    "misconceptions": [
        {"misconception_id": "MIS-1", "kc_id": "POLYMORPHISM", "type": "conceptual_confusion",
         "description": "混淆静态/动态类型", "severity": 0.78, "confidence": 0.82,
         "occurrence_count": 4, "status": "active"},
    ],
    "behavior": {"activity_count_30d": 18, "streak_days": 4, "recent_topics": ["多态"]},
    "state_version": 37,
    "updated_at": "2026-08-10T12:00:00Z",
}


def test_parse_course_state_fields():
    state = parse_course_state(PARTNER_COURSE_RAW)
    assert state.user_id == "STU-001"
    assert state.course_id == "JAVA-OOP"
    assert state.progress == 0.31
    assert state.state_version == 37
    assert state.freshness == "fresh"
    kc = state.get_knowledge("POLYMORPHISM")
    assert kc.mastery == 0.24
    assert kc.confidence == 0.78
    assert state.abilities["understanding"].score == 0.30
    # 数值型能力兼容
    assert state.abilities["application"].score == 0.31
    assert state.misconceptions[0].status == "active"


def test_parse_course_state_tolerates_wrappers_and_missing():
    wrapped = {"data": PARTNER_COURSE_RAW}
    state = parse_course_state(wrapped)
    assert state.progress == 0.31
    empty = parse_course_state(None)
    assert empty.knowledge == []
    assert empty.freshness == "fresh"


def test_make_empty_course_state_freshness_missing():
    state = make_empty_course_state("U1", "C1")
    assert state.freshness == "missing"


def test_parse_global_state_goals_and_preferences():
    raw = {
        "profile": {"user_id": "U1", "display_name": "张三"},
        "goals": [
            {"goal_id": "G1", "course_id": "JAVA-OOP", "goal_name": "实训",
             "target": "成绩管理", "priority": 1, "status": "active", "progress": 0.3}
        ],
        "preferences": {
            "preferred_mode": "example_driven",
            "mode_effectiveness": {"worked_example": {"score": 0.82, "confidence": 0.76, "sample_size": 14}},
            "pace_factor": 0.9,
        },
    }
    g = parse_global_state(raw)
    assert g.profile.display_name == "张三"
    assert g.goals[0].goal_id == "G1"
    assert g.preferences.mode_effectiveness["worked_example"].sample_size == 14
