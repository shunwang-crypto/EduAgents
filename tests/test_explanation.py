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
from edu_agent.application.explanation.context_builder import ExplanationContext
from edu_agent.application.explanation.generator import (
    _candidate_sections,
    _depth_requirements,
    _llm_blocks,
    _normalize_latex_markdown,
    _normalize_block,
    _validate_trie_prefix_diagrams,
)
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
    # Offline fallback is intentionally evidence-honest: a placeholder KC
    # description produces one explicit degraded block rather than generic prose.
    assert len(exp["blocks"]) >= 1
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


def _ctx(**overrides):
    values = dict(
        course_id="c", course_title="课程", goal="",
        kc_id="kc", kc_title="知识点", kc_description="一个概念的真实描述",
        kc_category="core", kc_difficulty="medium", step_title="知识点",
        step_objective="理解定义和适用条件", step_minutes=30,
    )
    values.update(overrides)
    return ExplanationContext(**values)


def test_candidate_pool_math_does_not_force_code():
    candidates = _candidate_sections(_ctx(
        kc_title="导数", kc_description="函数变化率的数学定义", kc_category="mathematics",
    ))
    assert "formula" in candidates
    assert "code_walkthrough" not in candidates


def test_candidate_pool_programming_can_offer_code():
    candidates = _candidate_sections(_ctx(
        kc_title="Python 函数", kc_description="定义参数和返回值", kc_category="programming",
    ))
    assert "code_walkthrough" in candidates


def test_candidate_pool_trie_offers_structured_diagram():
    candidates = _candidate_sections(_ctx(
        kc_title="Trie 插入算法", kc_description="前缀树节点与边的结构", kc_category="programming",
    ))
    assert "diagram" in candidates


def test_simple_concept_does_not_force_formula_or_table():
    candidates = _candidate_sections(_ctx(
        kc_title="颜色", kc_description="颜色是视觉感知中的一种属性", kc_category="concept",
    ))
    assert "formula" not in candidates
    assert "table" not in candidates


def test_complex_knowledge_requires_long_form_depth():
    minimum, target = _depth_requirements(_ctx(
        kc_title="微积分与梯度基础",
        kc_description="偏导数、链式法则与梯度下降",
        kc_category="mathematics",
    ))
    assert minimum >= 10_000
    assert target > minimum


def test_simple_concept_can_remain_short():
    assert _depth_requirements(_ctx(
        kc_title="颜色",
        kc_description="颜色是视觉感知的一种属性",
        kc_category="concept",
    )) == (0, 0)


def test_markdown_normalization_restores_paragraphs_without_breaking_nabla():
    raw = "第一段。\\n第二段包含 $\\nabla f$。"
    normalized = _normalize_latex_markdown(raw)
    assert "第一段。\n第二段" in normalized
    assert "$\\nabla f$" in normalized


def test_code_walkthrough_promotes_fenced_code_to_structured_renderer_field():
    block = ExplanationBlock(
        type=BlockType.CODE_WALKTHROUGH,
        title="插入实现",
        content="说明\n```python\\nclass Trie:\\n    pass\\n```\n逐行解释",
    )
    normalized = _normalize_block(block)
    assert normalized.data["code"] == "class Trie:\n    pass"
    assert "```" not in normalized.content
    assert normalized.content == "说明\n\n逐行解释"


def test_ascii_trie_tree_is_normalized_without_changing_app_semantics():
    block = ExplanationBlock(
        type=BlockType.DIAGRAM,
        title='插入 "app" 后的树结构',
        content="""root
 └── 'a' (is_end: False)
      └── 'p' (is_end: False)
           └── 'p' (is_end: True)
                └── 'l' (is_end: False)
                     └── 'e' (is_end: True)""",
    )
    normalized = _normalize_block(block)
    assert normalized.content == ""
    assert normalized.data["diagram_type"] == "tree"
    nodes = normalized.data["nodes"]
    edges = normalized.data["edges"]
    assert len(nodes) == 6
    assert len(edges) == 5
    assert [edge["source"] for edge in edges] == [
        "root", "tree-1", "tree-2", "tree-3", "tree-4",
    ]
    assert nodes[3]["label"].startswith("p ")
    assert nodes[3]["is_end"] is True
    assert nodes[4]["label"].startswith("l ")
    assert edges[3]["source"] == nodes[3]["id"]


def test_ascii_tree_parser_preserves_branch_parentage():
    block = ExplanationBlock(
        type=BlockType.DIAGRAM,
        title="Trie 分支",
        content="""root
├── 'a' (is_end: False)
│   ├── 'b' (is_end: True)
│   └── 'c' (is_end: True)
└── 'd' (is_end: True)""",
    )
    normalized = _normalize_block(block)
    edges = normalized.data["edges"]
    assert [(edge["source"], edge["target"]) for edge in edges] == [
        ("root", "tree-1"),
        ("tree-1", "tree-2"),
        ("tree-1", "tree-3"),
        ("root", "tree-4"),
    ]


def test_trie_app_diagram_semantic_guard_accepts_preserved_suffix():
    block = _normalize_block(ExplanationBlock(
        type=BlockType.DIAGRAM,
        title='插入 "app" 后的树结构',
        content="""root
 └── 'a' (is_end: False)
      └── 'p' (is_end: False)
           └── 'p' (is_end: True)
                └── 'l' (is_end: False)
                     └── 'e' (is_end: True)""",
    ))
    _validate_trie_prefix_diagrams(
        _ctx(kc_title="Trie 插入", kc_description="前缀树插入算法"),
        [block],
    )


def test_trie_app_diagram_semantic_guard_rejects_new_branch_or_lost_suffix():
    invalid = ExplanationBlock(
        type=BlockType.DIAGRAM,
        title='插入 "app" 后的树结构',
        data={
            "diagram_type": "tree",
            "nodes": [
                {"id": "root", "label": "root"},
                {"id": "a", "label": "a"},
                {"id": "p1", "label": "p"},
                {"id": "p2", "label": "p", "is_end": True},
                {"id": "new", "label": "app", "is_end": True},
            ],
            "edges": [
                {"source": "root", "target": "a"},
                {"source": "a", "target": "p1"},
                {"source": "p1", "target": "p2"},
                {"source": "p2", "target": "new"},
            ],
        },
    )
    with pytest.raises(RuntimeError, match="保留 a-p-p-l-e 路径"):
        _validate_trie_prefix_diagrams(
            _ctx(kc_title="Trie 插入", kc_description="前缀树插入算法"),
            [invalid],
        )


def test_non_tree_markdown_is_not_misclassified_as_ascii_tree():
    block = ExplanationBlock(
        type=BlockType.DIAGRAM,
        title="函数关系",
        content="平方根 root 是普通说明，不包含树形分支。",
    )
    normalized = _normalize_block(block)
    assert normalized.data == {}
    assert normalized.content == "平方根 root 是普通说明，不包含树形分支。"


def test_offline_fallback_has_no_planning_sections_or_generic_learning_advice(learner, made_course):
    uid, cid, plan_id, step_id, _ = made_course
    exp = ExplanationService(learner).get_explanation(uid, cid, plan_id, step_id)
    raw = str(exp)
    for marker in ("为什么现在学", "知识网络中的位置", "学习路线", "怎么动手把它学会", "与相邻知识点的关系"):
        assert marker not in raw
    assert "根据学习主题补充必要基础知识" not in raw


def test_llm_diagram_is_about_the_current_knowledge_not_the_learning_route(monkeypatch):
    import json
    from langchain_core.runnables import RunnableLambda

    payload = {
        "title": "梯度下降",
        "objective": "理解参数如何更新",
        "blocks": [
            {
                "type": "diagram", "title": "参数更新过程", "content": "误差驱动参数更新。",
                "data": {"nodes": [{"id": "loss", "label": "损失"}, {"id": "update", "label": "更新参数"}],
                         "edges": [{"source": "loss", "target": "update", "label": "梯度"}]},
            },
            {"type": "orientation", "title": "为什么现在学它？", "content": "规划话术", "data": {}},
        ],
    }
    monkeypatch.setattr(
        "edu_agent.core.llm.get_kb_llm",
        lambda temperature=0.4: RunnableLambda(lambda _: json.dumps(payload, ensure_ascii=False)),
    )
    blocks = _llm_blocks(_ctx(kc_title="梯度下降", kc_category="mathematics"), ["concept", "diagram"])
    assert [b.type for b in blocks] == [BlockType.DIAGRAM]
    assert blocks[0].data["edges"][0]["source"] == "loss"


def test_llm_blocks_strip_google_thought_wrapper(monkeypatch):
    import json
    from langchain_core.runnables import RunnableLambda

    payload = {
        "title": "导数",
        "objective": "理解变化率",
        "blocks": [{
            "type": "concept",
            "title": "导数是什么",
            "content": "导数描述函数在一点附近的瞬时变化率。",
            "data": {},
            "source_refs": [],
        }],
    }
    response = "<thought>internal reasoning</thought>" + json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(
        "edu_agent.core.llm.get_kb_llm",
        lambda temperature=0.4: RunnableLambda(lambda _: response),
    )
    blocks = _llm_blocks(_ctx(kc_title="导数", kc_category="mathematics"), ["concept"])
    assert len(blocks) == 1
    assert blocks[0].title == "导数是什么"


def test_llm_blocks_accept_latex_backslashes_in_json(monkeypatch):
    import json
    from langchain_core.runnables import RunnableLambda

    payload = {
        "title": "导数",
        "objective": "理解变化率",
        "blocks": [{
            "type": "formula",
            "title": "导数公式",
            "content": "公式中的梯度与分式为 \\nabla f = \\frac{\\partial f}{\\partial x}。",
            "data": {"latex": "\\begin{pmatrix}\\nabla f\\end{pmatrix}"},
            "source_refs": [],
        }],
    }
    # Simulate a model that emits the LaTeX backslash unescaped in JSON.
    response = (
        json.dumps(payload, ensure_ascii=False)
        .replace("\\\\partial", "\\partial")
        .replace("\\\\nabla", "\\nabla")
        .replace("\\\\frac", "\\frac")
        .replace("\\\\begin", "\\begin")
        .replace("\\\\end", "\\end")
    )
    monkeypatch.setattr(
        "edu_agent.core.llm.get_kb_llm",
        lambda temperature=0.4: RunnableLambda(lambda _: response),
    )
    blocks = _llm_blocks(_ctx(kc_title="导数", kc_category="mathematics"), ["formula"])
    assert len(blocks) == 1
    assert "\\nabla" in blocks[0].content
    assert "\\frac" in blocks[0].content
