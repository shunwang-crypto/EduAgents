"""V4 最终任务契约测试。

覆盖 §70-81：
- explicit prerequisite graph（不产生 dense 边）
- Stage 不产生 edge
- multi-prerequisite
- cycle reject
- current + future route（locked 仍在 primary_route）
- active subgraph = goal prerequisite closure
- tie-break 由 StudyPlan.seq 决定（非 hash id）
- PREREQUISITE_FOR_GOAL 只对 goal ancestor
- UNKNOWN PlanBrief
- critical path 是真实最长 DAG path
- Course title 不丢失领域信息
- completion != mastery
"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan, update_step_status
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.application.plan_brief_service import PlanBriefService
from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map
from edu_agent.workflows.study_plan.schemas import (
    ConceptSpec,
    DecompositionResult,
    LearningStageSuggestion,
    StudentInput,
)


def _stub_plan(monkeypatch, km, decomposition=None):
    import edu_agent.application.study_plan_service as sps

    def fake(*args, **kwargs):
        return {
            "knowledge_map": km,
            "final_plan": "P",
            "plan_steps": [],
            "goal": "g",
            "student_input": None,
            "decomposition": decomposition,
            "analysis": None,
            "lesson_cache": {},
        }

    monkeypatch.setattr(sps, "run_study_plan_workflow", fake)


@pytest.fixture
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "learner.db"))


def _three_stages():
    return [
        LearningStageSuggestion(stage_id="stage-1", title="基础准备", objective="x", order=1),
        LearningStageSuggestion(stage_id="stage-2", title="核心学习", objective="x", order=2),
        LearningStageSuggestion(stage_id="stage-3", title="综合应用", objective="x", order=3),
    ]


def _concept(tid, title, cat, refs, stage=2, is_target=False, diff="intermediate"):
    return ConceptSpec(
        temp_id=tid, title=title, summary=title, category=cat,
        content_type="code", difficulty=diff, stage_order=stage,
        prerequisite_refs=refs, is_target=is_target,
        learning_objective=f"能够实现 {title}",
    )


# ---------------------------------------------------------------------------
# §70-73：Graph 边只来自 explicit prerequisite_refs
# ---------------------------------------------------------------------------


def test_explicit_prerequisite_only():
    """A→B→C；禁止自动 A→C。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", ["A"], 2),
            _concept("C", "C", "target", ["B"], 2, is_target=True),
        ],
        target_refs=["C"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    km = build_knowledge_map(StudentInput(topic="T", days=5, daily_time="60分钟", goal="G"), dec)
    # nodes id == temp_id（canonicalizer 后续映射），edge 由 prerequisites 表达
    # prerequisites 是依赖方向（node 依赖 prereq），因此 (pre, dep) 构成 prerequisite edge。
    edges = {(p, n.id) for n in km.nodes for p in n.prerequisites}
    assert ("A", "B") in edges
    assert ("B", "C") in edges
    assert ("A", "C") not in edges


def test_stage_does_not_create_edge():
    """B、C 同属 Stage2 但不声明前置 → 不能自动 B→C 或 C→B。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", [], 2),
            _concept("C", "C", "target", [], 2, is_target=True),
        ],
        target_refs=["C"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    km = build_knowledge_map(StudentInput(topic="T", days=5, daily_time="60分钟", goal="G"), dec)
    edges = {(p, n.id) for n in km.nodes for p in n.prerequisites}
    assert ("B", "C") not in edges
    assert ("C", "B") not in edges


def test_legacy_fallback_sparse_chain():
    """§8：legacy learning_sequence 生成 sparse 依赖链，不产生 dense graph。"""
    dec = DecompositionResult(
        prerequisite_concepts=["Python", "NumPy"],
        core_concepts=["PyTorch", "Neural Network"],
        learning_sequence=["Python", "NumPy", "PyTorch", "Neural Network"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    km = build_knowledge_map(StudentInput(topic="T", days=5, daily_time="60分钟", goal="G"), dec)
    # learning_sequence 4 个概念 + 空 Stage-3 的综合应用兜底节点（三阶段结构不变式）
    ids = [n.id for n in km.nodes]
    assert {"python", "numpy", "pytorch", "neural_network"} <= set(ids)
    assert len(ids) >= 4
    edges = {(p, n.id) for n in km.nodes for p in n.prerequisites}
    # 稀疏链：Python→NumPy→PyTorch→Neural Network，每个节点最多依赖前一个
    assert ("python", "numpy") in edges
    assert ("numpy", "pytorch") in edges
    assert ("pytorch", "neural_network") in edges
    # 非 dense：不存在越级边
    assert ("python", "pytorch") not in edges
    assert ("python", "neural_network") not in edges
    assert ("numpy", "neural_network") not in edges


def test_multi_prerequisite():
    """A→C, B→C（multi-prereq 精确）。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", [], 1),
            _concept("C", "C", "target", ["A", "B"], 2, is_target=True),
        ],
        target_refs=["C"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    km = build_knowledge_map(StudentInput(topic="T", days=5, daily_time="60分钟", goal="G"), dec)
    edges = {(p, n.id) for n in km.nodes for p in n.prerequisites}
    assert ("A", "C") in edges
    assert ("B", "C") in edges


def test_cycle_rejected_by_canonicalizer(learner, monkeypatch):
    """A prereq=[C], B prereq=[A], C prereq=[B] → validator reject。"""
    from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode
    from edu_agent.workflows.study_plan.canonicalizer import KnowledgeMapCanonicalizer

    ks = [
        KnowledgeNode(id="A", title="A", category="core", summary="A", prerequisites=["C"],
                      difficulty="easy", estimated_minutes=30, stage_id="s1", stage_title="s",
                      stage_order=1, canonical_key="A", learning_objective="o"),
        KnowledgeNode(id="B", title="B", category="core", summary="B", prerequisites=["A"],
                      difficulty="easy", estimated_minutes=30, stage_id="s1", stage_title="s",
                      stage_order=1, canonical_key="B", learning_objective="o"),
        KnowledgeNode(id="C", title="C", category="core", summary="C", prerequisites=["B"],
                      difficulty="easy", estimated_minutes=30, stage_id="s1", stage_title="s",
                      stage_order=1, canonical_key="C", learning_objective="o"),
    ]
    km = KnowledgeMap(topic="T", nodes=ks, recommended_path=["A", "B", "C"])
    res = KnowledgeMapCanonicalizer("C1", "T", "g").canonicalize(km)
    assert res.course is None
    assert any(e.kind == "cycle" for e in res.validation_errors)


# ---------------------------------------------------------------------------
# §74-77：current + future route / active subgraph / tie-break / goal ancestor
# ---------------------------------------------------------------------------


def _setup_plan(learner, monkeypatch, topic, nodes, decomposition):
    from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode

    ks = []
    for (nid, title, pre, cat, diff, target) in nodes:
        ks.append(KnowledgeNode(
            id=nid, title=title, category=cat, summary=title, prerequisites=list(pre),
            difficulty=diff, estimated_minutes=30, stage_id="s1", stage_title="s",
            stage_order=1, canonical_key=nid, learning_objective=f"掌握 {title}",
        ))
    km = KnowledgeMap(topic=topic, nodes=ks, recommended_path=[n[0] for n in nodes])
    _stub_plan(monkeypatch, km, decomposition=decomposition)
    uid = f"v4-{topic}"
    cid = create_course(uid, topic, goal="掌握", learner=learner)["course_id"]
    generate_plan(uid, cid, goal="掌握", learner=learner)
    return uid, cid


def test_offline_integration_graph_not_empty():
    """§9：OFFLINE/deterministic workflow 生成的图必须有边、有 target、路由≥2。"""
    from edu_agent.workflows.study_plan.schemas import AnalysisResult
    from edu_agent.workflows.study_plan.workflow import _fallback_decomposition

    analysis = AnalysisResult(
        topic="PyTorch 深度学习入门",
        level_summary="入门",
        goal_summary="掌握 PyTorch，并学习 CNN、RNN、Transformer",
        prerequisites=["Python 编程基础", "线性代数", "微积分"],
        need_web_search=False,
        search_queries=[],
    )
    dec = _fallback_decomposition(
        StudentInput(topic="PyTorch 深度学习入门", days=14, daily_time="60分钟",
                     goal="掌握 PyTorch，并学习 CNN、RNN、Transformer"),
        analysis,
        exc=None,
    )
    assert len(dec.concepts) > 3
    # 非 0 edges：每个概念（除首个）依赖前一个序列节点
    edge_count = sum(1 for c in dec.concepts for _ in c.prerequisite_refs)
    assert edge_count > 0
    # target 至少一个
    assert len(dec.target_refs) > 0

    km = build_knowledge_map(
        StudentInput(topic="PyTorch 深度学习入门", days=14, daily_time="60分钟",
                     goal="掌握 PyTorch，并学习 CNN、RNN、Transformer"),
        dec,
    )
    assert len(km.nodes) > 3
    edge_count2 = sum(1 for n in km.nodes for _ in n.prerequisites)
    assert edge_count2 > 0
    # primary_route ≥ 2：走真实 DAG 边
    from edu_agent.domain.learning.course import Course
    from edu_agent.domain.learning.knowledge_component import KnowledgeComponent
    from edu_agent.domain.learning.kc_relation import KCRelation
    from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy

    kcs = [KnowledgeComponent(kc_id=n.id, title=n.title) for n in km.nodes]
    relations = [
        KCRelation(from_kc=p, to_kc=n.id, relation="prerequisite")
        for n in km.nodes for p in n.prerequisites
    ]
    course = Course(course_id="C", title="PyTorch", components=kcs, relations=relations)
    targets = dec.target_refs
    policy = HeuristicAdaptivePolicy(course, target_kcs=targets)
    route = policy.primary_route({}, {}, {}, start_kc=km.nodes[0].id)
    assert len(route) >= 2
    # primary_route 相邻节点必须有真实 edge（route[i] 是 route[i+1] 的前置）
    for i in range(len(route) - 1):
        assert route[i] in course.prerequisites(route[i + 1])


def test_current_and_future_route(learner, monkeypatch):
    """A→B→C 全 UNKNOWN：current=A, B/C locked, primary_route=[A,B,C]。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", ["A"], 2),
            _concept("C", "C", "target", ["B"], 2, is_target=True),
        ],
        target_refs=["C"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "route", [
        ("nodea", "A", [], "core", "easy", False),
        ("nodeb", "B", ["nodea"], "core", "easy", False),
        ("nodec", "C", ["nodeb"], "core", "hard", True),
    ], dec)
    m = LearningMapService(learner).build(uid, cid)
    assert m.current_recommended_kc == "nodea"
    node_b = next(n for n in m.nodes if n.id == "nodeb")
    node_c = next(n for n in m.nodes if n.id == "nodec")
    assert node_b.locked is True
    assert node_c.locked is True
    assert m.primary_route == ["nodea", "nodeb", "nodec"]


def test_active_subgraph_closure(learner, monkeypatch):
    """A→C, B→C, C→D, target=D：active_subgraph_nodes 含 A,B,C,D。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", [], 1),
            _concept("C", "C", "core", ["A", "B"], 2),
            _concept("D", "D", "target", ["C"], 2, is_target=True),
        ],
        target_refs=["D"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "sub", [
        ("nodea", "A", [], "core", "easy", False),
        ("nodeb", "B", [], "core", "easy", False),
        ("nodec", "C", ["nodea", "nodeb"], "core", "easy", False),
        ("noded", "D", ["nodec"], "core", "hard", True),
    ], dec)
    m = LearningMapService(learner).build(uid, cid)
    assert set(m.active_subgraph_nodes) == {"nodea", "nodeb", "nodec", "noded"}
    # supporting prerequisite（A/B→C）不消失
    assert any(e.source == "nodea" and e.target == "nodec" for e in m.active_subgraph_edges)
    assert any(e.source == "nodeb" and e.target == "nodec" for e in m.active_subgraph_edges)


def test_tie_break_by_seq_not_kc_id(learner, monkeypatch):
    """z_root seq=1, a_root seq=2：即使 a_root 字典序更小，current 仍为 z_root。"""
    dec = DecompositionResult(
        concepts=[
            _concept("z_root", "Z基础", "core", [], 1),
            _concept("a_root", "A基础", "core", [], 1),
        ],
        target_refs=[],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "tie", [
        ("z_root", "Z基础", [], "core", "easy", False),
        ("a_root", "A基础", [], "core", "easy", False),
    ], dec)
    m = LearningMapService(learner).build(uid, cid)
    assert m.current_recommended_kc == "z_root"


def test_goal_ancestor_reason(learner, monkeypatch):
    """A→B→C target=C：A/B 有 PREREQUISITE_FOR_GOAL，C 没有。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", ["A"], 2),
            _concept("C", "C", "target", ["B"], 2, is_target=True),
        ],
        target_refs=["C"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "anc", [
        ("nodea", "A", [], "core", "easy", False),
        ("nodeb", "B", ["nodea"], "core", "easy", False),
        ("nodec", "C", ["nodeb"], "core", "hard", True),
    ], dec)
    m = LearningMapService(learner).build(uid, cid)
    rel = {n.id for n in m.nodes if "PREREQUISITE_FOR_GOAL" in n.reason_codes}
    assert "nodea" in rel
    assert "nodeb" in rel
    assert "nodec" not in rel


# ---------------------------------------------------------------------------
# §78-80：UNKNOWN PlanBrief / critical path / course title
# ---------------------------------------------------------------------------


def test_plan_brief_unknown(learner, monkeypatch):
    """所有 mastery=None：known=[] gap=[] unassessed=所有相关 KC。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "target", ["A"], 2, is_target=True),
        ],
        target_refs=["B"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "brief", [
        ("A", "A", [], "core", "easy", False),
        ("B", "B", ["A"], "core", "hard", True),
    ], dec)
    brief = PlanBriefService(learner).get(uid, cid)
    assert brief["known_skills"] == []
    assert brief["skill_gaps"] == []
    assert {"A", "B"} <= set(brief["unassessed_skills"])


def test_critical_path_is_longest(learner, monkeypatch):
    """A→B→C→D 与 E→F；主链选 D：critical path=A,B,C,D。"""
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "core", ["A"], 2),
            _concept("C", "C", "core", ["B"], 2),
            _concept("D", "D", "target", ["C"], 2, is_target=True),
            _concept("E", "E", "core", [], 1),
            _concept("F", "F", "target", ["E"], 2, is_target=True),
        ],
        target_refs=["D", "F"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "crit", [
        ("A", "A", [], "core", "easy", False),
        ("B", "B", ["A"], "core", "easy", False),
        ("C", "C", ["B"], "core", "easy", False),
        ("D", "D", ["C"], "core", "hard", True),
        ("E", "E", [], "core", "easy", False),
        ("F", "F", ["E"], "core", "easy", True),
    ], dec)
    brief = PlanBriefService(learner).get(uid, cid)
    names = [p["name"] for p in brief["critical_path"]]
    assert names[:4] == ["A", "B", "C", "D"]


def test_course_title_kept():
    """§32/§80：'PyTorch 深度学习入门' 不能变成 '入门'。"""
    from edu_agent.application.course_service import create_course

    learner = LearnerModelService(db_path=":memory:")
    course = create_course("u1", "PyTorch 深度学习入门", goal="g", learner=learner)
    assert course["display_name"] == "PyTorch 深度学习入门"
    course2 = create_course("u2", "Python 数据分析进阶", goal="g", learner=learner)
    assert course2["display_name"] == "Python 数据分析进阶"


# ---------------------------------------------------------------------------
# §81：completion != mastery
# ---------------------------------------------------------------------------


def test_completion_does_not_change_mastery(learner, monkeypatch):
    dec = DecompositionResult(
        concepts=[
            _concept("A", "A", "core", [], 1),
            _concept("B", "B", "target", ["A"], 2, is_target=True),
        ],
        target_refs=["B"],
        difficulty_points=[],
        stages=_three_stages(),
        application_directions=[],
    )
    uid, cid = _setup_plan(learner, monkeypatch, "compl", [
        ("A", "A", [], "core", "easy", False),
        ("B", "B", ["A"], "core", "hard", True),
    ], dec)
    plan = learner.repo.get_plan(uid, cid)
    step = learner.repo.list_plan_steps(plan["plan_id"])[0]
    mastery_before = learner.build_bundle(uid, cid).course_state.knowledge
    m_before = {k.kc_id: k.mastery for k in mastery_before}
    # not_started → in_progress → completed
    update_step_status(uid, cid, step["step_id"], "in_progress", learner=learner)
    update_step_status(uid, cid, step["step_id"], "completed", learner=learner)
    mastery_after = learner.build_bundle(uid, cid).course_state.knowledge
    m_after = {k.kc_id: k.mastery for k in mastery_after}
    # mastery 不应因完成讲解而变化
    assert m_before.get("A") == m_after.get("A")
    assert m_before.get("B") == m_after.get("B")
    refreshed = learner.repo.list_plan_steps(plan["plan_id"])
    assert refreshed[0]["status"] == "completed"
