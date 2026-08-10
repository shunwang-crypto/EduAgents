"""LearnerState Schema 测试：多课程 / mastery 与 confidence 分离 / misconception / metadata。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.integrations.learner_state.schemas import (  # noqa: E402
    CourseLearnerState,
    GlobalLearnerState,
    KnowledgeItem,
    LearnerStateBundle,
    Misconception,
)


def test_knowledge_item_mastery_confidence_separated():
    item = KnowledgeItem(kc_id="POLYMORPHISM", mastery=0.20, confidence=0.95)
    assert item.mastery == 0.20
    assert item.confidence == 0.95
    assert item.status == "unknown"


def test_course_state_multi_course_isolation():
    java = CourseLearnerState(user_id="U1", course_id="JAVA-OOP")
    transformer = CourseLearnerState(user_id="U1", course_id="TRANSFORMER")
    java.knowledge = [KnowledgeItem(kc_id="POLYMORPHISM", mastery=0.24)]
    transformer.knowledge = [KnowledgeItem(kc_id="ATTENTION", mastery=0.8)]
    # Java 请求不得加载 Transformer mastery
    assert {k.kc_id for k in java.knowledge} == {"POLYMORPHISM"}
    assert {k.kc_id for k in transformer.knowledge} == {"ATTENTION"}


def test_misconception_structured():
    m = Misconception(
        misconception_id="MIS-1",
        kc_id="POLYMORPHISM",
        type="conceptual_confusion",
        description="混淆静态类型与动态类型",
        severity=0.78,
        confidence=0.82,
        occurrence_count=4,
        status="active",
    )
    assert m.type == "conceptual_confusion"
    assert m.status == "active"
    assert m.severity > 0.7


def test_global_state_defaults_and_goals():
    g = GlobalLearnerState()
    assert g.profile.user_id == ""
    assert g.goals == []


def test_bundle_carries_version_and_freshness():
    state = CourseLearnerState(
        user_id="U1", course_id="JAVA-OOP", state_version=37, freshness="mock"
    )
    bundle = LearnerStateBundle(user_id="U1", course_id="JAVA-OOP", course_state=state)
    assert bundle.course_state.state_version == 37
    assert bundle.course_state.freshness == "mock"
