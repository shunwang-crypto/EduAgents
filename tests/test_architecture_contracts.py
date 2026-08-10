"""架构契约测试：无 partner / 无 quiz / 无本地 mastery ±delta / 无第二套画像。

静态扫描 + 关键 schema 断言，防止旧架构回归。
"""

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.adaptive.schemas import FORBIDDEN_ACTIONS, AdaptiveDecision, PED_ACTIONS  # noqa: E402


def _src_py_files():
    return list((SRC_DIR / "edu_agent").rglob("*.py"))


# ----------------------------------------------------------------------
# Partner 架构必须不存在
# ----------------------------------------------------------------------
def test_no_partner_remote_provider():
    banned = [
        "integrations.learner_state",
        "remote_provider",
        "MockLearnerStateProvider",
        "LearnerStateProvider",
        "LEARNER_STATE_BASE_URL",
        "LEARNER_STATE_API_KEY",
        "LEARNER_STATE_PROVIDER",
        "LEARNING_EVENT_DELIVERY",
        "event_emitter",
        "killoppen",
    ]
    haystack = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in _src_py_files()
    )
    for token in banned:
        assert token not in haystack, f"partner 残留：{token}"


def test_no_partner_env_in_settings():
    from edu_agent.config.settings import Settings

    fields = Settings.model_fields
    assert "learner_state_provider" not in fields
    assert "learner_state_base_url" not in fields
    assert "learner_state_api_key" not in fields
    assert "learning_event_delivery_url" not in fields
    assert "learner_model_db_path" in fields


# ----------------------------------------------------------------------
# Quiz / Practice / Mistake 业务必须不存在
# ----------------------------------------------------------------------
def test_no_quiz_practice_business():
    banned = [
        "workflows.quiz",
        "workflows import quiz",
        "PracticeDesigner",
        "QuizGeneration",
        "MistakeReflection",
        "mastery +=",
        "mastery -=",
        "correct:",
    ]
    haystack = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in _src_py_files()
    )
    for token in banned:
        assert token not in haystack, f"练习/quiz 残留：{token}"


def test_forbidden_actions_never_used():
    # 决策动作集不允许出现练习类动作
    for action in FORBIDDEN_ACTIONS:
        assert action not in PED_ACTIONS


# ----------------------------------------------------------------------
# 第二套画像（student_profile / old mastery）必须不存在
# ----------------------------------------------------------------------
def test_no_second_profile_engine():
    banned = ["core.student_profile", "core.mastery", "student_profile", "StudentProfile"]
    haystack = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in _src_py_files()
    )
    for token in banned:
        assert token not in haystack, f"第二套画像残留：{token}"


# ----------------------------------------------------------------------
# SQLite 是唯一画像真值
# ----------------------------------------------------------------------
def test_learner_model_uses_sqlite():
    from edu_agent.learner_model import db, sqlite_repository, service

    assert hasattr(db, "connect")
    assert hasattr(sqlite_repository, "SQLiteLearnerRepository")
    assert hasattr(service, "LearnerModelService")


def test_learner_model_tables_exist(tmp_path):
    from edu_agent.learner_model.db import get_connection

    conn = get_connection(str(tmp_path / "lm.db"))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "learners", "learner_profile_facts", "learning_goals",
        "learner_course_states", "learner_kc_states", "learner_abilities",
        "learner_preferences", "learner_misconceptions",
        "learner_semantic_memories", "learning_events",
        "profile_change_log", "learner_state_snapshots",
    }
    assert expected <= tables
    conn.close()


# ----------------------------------------------------------------------
# AdaptiveDecision 结构
# ----------------------------------------------------------------------
def test_decision_has_required_fields():
    decision = AdaptiveDecision(target_kc="POLYMORPHISM", depth="basic")
    assert decision.reason_codes == []
    assert decision.pedagogical_actions == []
    assert decision.learner_state_version is None
    assert decision.explain()  # 可解释输出


def test_no_practice_in_kb_workflow_prompts():
    from edu_agent.workflows.kb_qa import prompts as kb_prompts

    text = open(kb_prompts.__file__, encoding="utf-8").read()
    assert "练习题" not in text
    assert "quiz" not in text.lower()
