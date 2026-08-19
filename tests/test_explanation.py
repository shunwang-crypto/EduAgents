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
    assert exp["schema_version"] == 2
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


def test_validator_does_not_enforce_fixed_section_count():
    """Adaptive Rich Explanation 允许一个或很多 section，不套固定七段。"""
    validator = ExplanationValidator()
    one = StepExplanation(
        explanation_id="one", course_id="c", plan_id="p", step_id="s", kc_id="k",
        title="简单知识点",
        blocks=[ExplanationBlock(type="concept", title="完整解释", content="内容")],
    )
    many = StepExplanation(
        explanation_id="many", course_id="c", plan_id="p", step_id="s", kc_id="k",
        title="复杂知识点",
        blocks=[
            ExplanationBlock(type="concept", title=f"区段 {i}", content="可包含很长的 Markdown")
            for i in range(16)
        ],
    )
    assert validator.validate(one) == []
    assert validator.validate(many) == []


def test_deterministic_fallback_no_raw_ids(learner, made_course):
    """§40：确定性 fallback 的可见 block 文本不得包含 kc_ 内部 id。"""
    uid, cid, plan_id, step_id, kc_id = made_course
    # 强制离线（EDU_OFFLINE=1 已在文件顶部），走确定性 fallback
    exp = ExplanationService(learner).get_explanation(uid, cid, plan_id, step_id)
    # 用户可见的 block 内容 / data / title 不得含 kc_ 内部 id
    for block in exp["blocks"]:
        text = f"{block.get('title','')}{block.get('content','')}".lower()
        data = str(block.get("data", {})).lower()
        assert "kc_" not in text
        assert "kc_" not in data
    # 前置/后继使用人类名称（title），非 id
    all_text = " ".join(
        str(b.get("content", "")) + str(b.get("data", {})) for b in exp["blocks"]
    ).lower()
    assert "kc_" not in all_text


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
