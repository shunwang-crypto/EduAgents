"""Structured Explanation 测试：schema / 校验 / 缓存 / legacy / handoff。

禁止 Exercise（见 test_no_exercise）：Explanation 绝不返回 correct_answer / quiz 等。
"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.explanation.models import BlockType, ExplanationBlock, StepExplanation
from edu_agent.application.explanation.validator import ExplanationValidator
from edu_agent.application.explanation.service import ExplanationService, build_practice_handoff


def _stub_plan(monkeypatch, km):
    import edu_agent.application.study_plan_service as sps

    def fake(*args, **kwargs):
        return {
            "knowledge_map": km, "final_plan": "P", "plan_steps": [],
            "goal": "g", "student_input": None, "decomposition": None,
            "analysis": None, "lesson_cache": {},
        }

    monkeypatch.setattr(sps, "run_study_plan_workflow", fake)


@pytest.fixture
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "learner.db"))


@pytest.fixture
def km():
    from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode

    def kn(node_id, title, prereqs=(), difficulty="easy", category="core"):
        return KnowledgeNode(
            id=node_id, title=title, category=category, summary=f"{title} 描述",
            prerequisites=list(prereqs), difficulty=difficulty,
            estimated_minutes=30, stage_id="s1", stage_title="基础准备",
            stage_order=1, learning_objective=f"掌握 {title}",
        )

    return KnowledgeMap(
        topic="NumPy",
        nodes=[
            kn("numpy_array", "NumPy 数组基础", category="code"),
            kn("numpy_broadcasting", "NumPy 广播", ["numpy_array"], difficulty="hard", category="code"),
        ],
        recommended_path=["numpy_array", "numpy_broadcasting"],
    )


@pytest.fixture
def made_course(learner, monkeypatch, km):
    uid = "exp-user"
    cid = create_course(uid, "NumPy", goal="掌握数组计算与广播", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    plan = generate_plan(uid, cid, goal="掌握数组计算与广播", learner=learner)
    step = plan["steps"][0]
    return uid, cid, plan["plan_id"], step["step_id"], step["kc_id"]


def test_explanation_generated_and_valid(learner, made_course):
    uid, cid, plan_id, step_id, kc_id = made_course
    svc = ExplanationService(learner)
    exp = svc.get_explanation(uid, cid, plan_id, step_id)

    assert exp["step_id"] == step_id
    assert exp["kc_id"] == kc_id
    assert len(exp["blocks"]) >= 3
    valid_types = {t.value for t in BlockType}
    for b in exp["blocks"]:
        assert b["type"] in valid_types
        assert b["title"].strip()
    # kc_id 存在于 graph
    from edu_agent.application.course_graph_service import CourseGraphService
    course = CourseGraphService(learner._repo).load_active_graph(uid, cid).course
    assert course.kc_by_id(kc_id) is not None


def test_explanation_cache_same_hash_reuse(learner, made_course):
    uid, cid, plan_id, step_id, _ = made_course
    svc = ExplanationService(learner)
    exp1 = svc.get_explanation(uid, cid, plan_id, step_id)
    exp2 = svc.get_explanation(uid, cid, plan_id, step_id)
    assert exp1["context_hash"] == exp2["context_hash"]
    assert [b["title"] for b in exp1["blocks"]] == [b["title"] for b in exp2["blocks"]]


def test_explanation_has_no_exercise_content(learner, made_course):
    uid, cid, plan_id, step_id, _ = made_course
    svc = ExplanationService(learner)
    exp = svc.get_explanation(uid, cid, plan_id, step_id)
    raw = str(exp).lower()
    for forbidden in ("correct_answer", "submitted_answer", "score", "grading", "quiz", "options"):
        assert forbidden not in raw


def test_explanation_validator_rejects_invalid(learner):
    from pydantic import ValidationError

    v = ExplanationValidator()
    # 非法 block type → pydantic 校验拒绝
    with pytest.raises(ValidationError):
        ExplanationBlock(type="not_a_type", title="x")  # type: ignore[arg-type]
    # 空 blocks → issue
    exp = StepExplanation(explanation_id="e", course_id="c", plan_id="p",
                          step_id="s", kc_id="k", title="t", blocks=[])
    issues = v.validate(exp)
    assert any("blocks is empty" in i.message for i in issues)
    # 含练习内容 → issue
    bad = StepExplanation(explanation_id="e2", course_id="c", plan_id="p",
                          step_id="s2", kc_id="k", title="t2",
                          blocks=[ExplanationBlock(type="concept", title="x",
                                                   content="请选择 correct_answer")])
    issues2 = v.validate(bad)
    assert any("forbidden practice content" in i.message for i in issues2)


def test_practice_handoff_interface_only(learner, made_course):
    uid, cid, plan_id, step_id, kc_id = made_course
    h = build_practice_handoff(uid, cid, plan_id, step_id, learner)
    assert h.kc_id == kc_id
    assert h.source == "study_plan"
    assert h.course_id == cid
    # 只定义接口，不含题目/判分
    d = h.model_dump()
    for forbidden in ("question", "options", "correct_answer", "score"):
        assert forbidden not in d
