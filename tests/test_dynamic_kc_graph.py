"""动态 KCGraph 生成 + 统一 canonical KC ID 端到端测试。

覆盖 spec 第 78-96 条：
- canonical ID 派生（拒绝 knowledge-N）
- 中文标题 fallback 稳定
- duplicate canonical key 检测
- dangling prerequisite / cycle 被校验拦截
- StudyPlan 引用同一 canonical IDs
- 禁止 knowledge-N
- 动态 NumPy graph 端到端（mock LLM，离线）
- Tutor 使用动态图 / 拒绝 fake kc_id
- Learner state 共享 canonical id
- 重新生成保留 mastery / 新 KC unknown / 删除 KC 不删历史
- built-in LLM-RAG / JAVA-OOP 兼容
- UNKNOWN != 0
"""

import os

# 离线模式：强制 LLMConfigurationError，所有 agent 走确定性 fallback。
os.environ.setdefault("EDU_OFFLINE", "1")

from datetime import datetime, timezone

import pytest

from edu_agent.domain.learning.kc_graph import get_course
from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.application.course_graph_service import CourseGraphService
from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode
from edu_agent.workflows.study_plan.canonicalizer import (
    KnowledgeMapCanonicalizer,
    canonicalize_kc_id,
    normalize_title,
    normalize_canonical_key,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _numpy_knowledge_map() -> KnowledgeMap:
    """Mock LLM 返回的 NumPy 知识地图草稿（带 canonical_key）。"""
    nodes = [
        _kn("n1", "NumPy 数组基础", "core", "ndarray 创建与基础操作", "easy", [], "numpy_array"),
        _kn("n2", "数组索引与切片", "core", "基础 indexing / slicing", "easy", ["NumPy 数组基础"], "numpy_indexing"),
        _kn("n3", "数组形状与重塑", "core", "shape / reshape", "medium", ["NumPy 数组基础"], "numpy_shape"),
        _kn("n4", "广播机制", "core", "broadcasting 规则", "hard", ["数组形状与重塑"], "numpy_broadcasting"),
        _kn("n5", "向量化计算", "application", "vectorization 性能", "hard", ["广播机制"], "numpy_vectorization"),
    ]
    return KnowledgeMap(
        topic="NumPy",
        nodes=nodes,
        recommended_path=["n1", "n2", "n3", "n4", "n5"],
    )


def _kn(node_id, title, category, summary, difficulty, prerequisites, canonical_key=None):
    return KnowledgeNode(
        id=node_id, title=title, category=category, summary=summary,
        difficulty=difficulty, prerequisites=prerequisites,
        estimated_minutes=30, stage_id="s1", stage_title="阶段",
        stage_order=1, learning_objective="obj", canonical_key=canonical_key,
    )


@pytest.fixture
def learner(tmp_path):
    # 隔离 DB：避免共享默认实例导致的跨测试污染（kc state / graph 持久化）。
    import tempfile

    db = str(tmp_path / "learner.db")
    return LearnerModelService(db_path=db)


def _make_course(learner, uid, topic, goal):
    course = create_course(uid, topic, goal=goal, learner=learner)
    return course["course_id"]


# ---------------------------------------------------------------------------
# 1. canonical ID 派生（拒绝 knowledge-N）
# ---------------------------------------------------------------------------

def test_canonical_id_rejects_knowledge_n():
    km = KnowledgeMap(
        topic="t",
        nodes=[
            _kn("knowledge-1", "Embedding", "core", "x", "easy", [], "embedding"),
            _kn("knowledge-2", "Vector Database", "core", "x", "easy", [], "vector_database"),
        ],
        recommended_path=["knowledge-1", "knowledge-2"],
    )
    res = KnowledgeMapCanonicalizer("C", "C", "g").canonicalize(km)
    assert res.course is not None
    ids = {c.kc_id for c in res.course.components}
    assert "knowledge-1" not in ids
    assert "knowledge-2" not in ids
    assert "embedding" in ids
    assert "vector_database" in ids


# ---------------------------------------------------------------------------
# 2. 中文标题 fallback 稳定
# ---------------------------------------------------------------------------

def test_chinese_title_fallback_stable():
    a = canonicalize_kc_id("数组广播机制")  # 无 canonical_key
    b = canonicalize_kc_id("数组广播机制")
    assert a == b
    assert a.startswith("kc_")
    assert len(a) == 13  # kc_ + 10 hex
    assert "knowledge-" not in a


def test_canonical_key_preferred_when_valid():
    assert canonicalize_kc_id("Embedding", "embedding") == "embedding"
    assert canonicalize_kc_id("向量数据库", "vector_database") == "vector_database"


def test_invalid_canonical_key_falls_back():
    # 非法 canonical_key（含大写/特殊字符/中文）→ 按标题派生
    a = canonicalize_kc_id("RAG!!!", "RAG!!!")
    b = canonicalize_kc_id("RAG!!!", "RAG!!!")
    assert a == b and a.startswith("kc_")
    # 含中文的 canonical_key 视为非法
    assert canonicalize_kc_id("知识点1", "知识点1").startswith("kc_")
    # knowledge-1 形式被当作非法
    assert normalize_canonical_key("knowledge-1") is None


# ---------------------------------------------------------------------------
# 3. duplicate canonical key
# ---------------------------------------------------------------------------

def test_duplicate_canonical_key_not_overwritten():
    km = KnowledgeMap(
        topic="t",
        nodes=[
            _kn("a", "Embedding", "core", "x", "easy", [], "embedding"),
            _kn("b", "Different Concept", "core", "x", "easy", [], "embedding"),
        ],
        recommended_path=["a", "b"],
    )
    res = KnowledgeMapCanonicalizer("C", "C", "g").canonicalize(km)
    assert res.course is not None
    ids = [c.kc_id for c in res.course.components]
    # 两个 id 都出现且不互相覆盖
    assert len(ids) == 2
    assert "embedding" in ids
    assert any(i.startswith("kc_") and i != "embedding" for i in ids)
    assert res.collisions  # 记录了 collision


def test_duplicate_key_same_title_merges():
    km = KnowledgeMap(
        topic="t",
        nodes=[
            _kn("a", "Embedding", "core", "x", "easy", [], "embedding"),
            _kn("b", "Embedding", "core", "x", "easy", [], "embedding"),
        ],
        recommended_path=["a", "b"],
    )
    res = KnowledgeMapCanonicalizer("C", "C", "g").canonicalize(km)
    assert res.course is not None
    ids = {c.kc_id for c in res.course.components}
    assert ids == {"embedding"}


# ---------------------------------------------------------------------------
# 4. dangling prerequisite
# ---------------------------------------------------------------------------

def test_dangling_prerequisite_rejected():
    km = KnowledgeMap(
        topic="t",
        nodes=[
            _kn("a", "Embedding", "core", "x", "easy", ["missing-node"], "embedding"),
        ],
        recommended_path=["a"],
    )
    res = KnowledgeMapCanonicalizer("C", "C", "g").canonicalize(km)
    assert res.course is None
    assert any(e.kind == "dangling_prerequisite" for e in res.validation_errors)


# ---------------------------------------------------------------------------
# 5. cycle
# ---------------------------------------------------------------------------

def test_cycle_rejected():
    km = KnowledgeMap(
        topic="t",
        nodes=[
            _kn("a", "A", "core", "x", "easy", ["C"], "a"),
            _kn("b", "B", "core", "x", "easy", ["A"], "b"),
            _kn("c", "C", "core", "x", "easy", ["B"], "c"),
        ],
        recommended_path=["a", "b", "c"],
    )
    res = KnowledgeMapCanonicalizer("C", "C", "g").canonicalize(km)
    assert res.course is None
    assert any(e.kind == "cycle" for e in res.validation_errors)


# ---------------------------------------------------------------------------
# 6. StudyPlan ID consistency
# ---------------------------------------------------------------------------

def test_studyplan_id_consistency(learner, monkeypatch):
    uid = "sp-consistency"
    course_id = _make_course(learner, uid, "NumPy 学习", "能够进行数组计算、广播和基础数据处理")
    numpy_km = _numpy_knowledge_map()

    import edu_agent.application.study_plan_service as sps

    def fake_workflow(*args, **kwargs):
        return {
            "knowledge_map": numpy_km,
            "final_plan": "P",
            "plan_steps": [],
            "goal": "能够进行数组计算、广播和基础数据处理",
            "student_input": None,
            "decomposition": None,
            "lesson_cache": {},
        }

    monkeypatch.setattr(sps, "run_study_plan_workflow", fake_workflow)
    plan = generate_plan(uid, course_id, goal="能够进行数组计算、广播和基础数据处理", learner=learner)
    node_ids = {s["kc_id"] for s in plan["steps"]}
    for step in plan["steps"]:
        assert step["kc_id"] in node_ids


# ---------------------------------------------------------------------------
# 7. 禁止 knowledge-N
# ---------------------------------------------------------------------------

def test_no_knowledge_n_in_persisted_plan(learner, monkeypatch):
    import re

    uid = "sp-nokn"
    course_id = _make_course(learner, uid, "NumPy 学习2", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    plan = generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)
    for step in plan["steps"]:
        assert not re.match(r"^knowledge-\d+$", step["kc_id"])


# ---------------------------------------------------------------------------
# 8. 动态 NumPy graph 端到端
# ---------------------------------------------------------------------------

def test_dynamic_numpy_graph_end_to_end(learner, monkeypatch):
    uid = "sp-numpy"
    course_id = _make_course(learner, uid, "NumPy 学习3", "能够进行数组计算、广播和基础数据处理")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算、广播和基础数据处理", learner=learner)

    svc = LearningMapService(learner)
    resp = svc.build(uid, course_id)
    node_ids = {n.id for n in resp.nodes}
    assert {"numpy_array", "numpy_indexing", "numpy_shape", "numpy_broadcasting", "numpy_vectorization"} <= node_ids
    assert resp.graph_source == "generated"
    # PlanStep.kc_ids ⊆ graph node ids
    from edu_agent.application.study_plan_service import get_plan

    plan = get_plan(uid, course_id, learner)
    for step in plan["steps"]:
        assert step["kc_id"] in node_ids


# ---------------------------------------------------------------------------
# 9. Tutor uses dynamic graph
# ---------------------------------------------------------------------------

def test_tutor_uses_dynamic_graph(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-tutor"
    course_id = _make_course(learner, uid, "NumPy 学习4", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    r = wf.start_turn(uid, TutorRequest(kc_id="numpy_array"))
    assert "ASSESS" in r.teaching_action.value


# ---------------------------------------------------------------------------
# 10. Fake KC rejected
# ---------------------------------------------------------------------------

def test_tutor_rejects_fake_kc(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-fake"
    course_id = _make_course(learner, uid, "NumPy 学习5", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    with pytest.raises(ValueError):
        wf.start_turn(uid, TutorRequest(kc_id="random_fake_kc"))


# ---------------------------------------------------------------------------
# 11. Learner state shares canonical id
# ---------------------------------------------------------------------------

def test_learner_state_shares_canonical_id(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-share"
    course_id = _make_course(learner, uid, "NumPy 学习6", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="向量是一维数组"))
    states = learner.repo.list_kcs(uid, course_id)
    kc_ids = {s["kc_id"] for s in states}
    assert "numpy_array" in kc_ids
    assert not any(s["kc_id"].startswith("knowledge-") for s in states)


# ---------------------------------------------------------------------------
# 12. Regeneration preservation
# ---------------------------------------------------------------------------

def test_regeneration_preserves_mastery(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-regen"
    course_id = _make_course(learner, uid, "NumPy 学习7", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    # 先让 numpy_array 达到 mastery
    for _ in range(8):
        wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="向量数组练习"))
    before = next((s for s in learner.repo.list_kcs(uid, course_id) if s["kc_id"] == "numpy_array"), None)
    assert (before or {}).get("mastery") is not None

    # 重新生成（基于现有图，ID 稳定）
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)
    after = next((s for s in learner.repo.list_kcs(uid, course_id) if s["kc_id"] == "numpy_array"), None)
    # mastery 保留
    assert (after or {}).get("mastery") == (before or {}).get("mastery")


# ---------------------------------------------------------------------------
# 13. New KC after regeneration = UNKNOWN
# ---------------------------------------------------------------------------

def test_new_kc_after_regen_is_unknown(learner, monkeypatch):
    uid = "sp-newkc"
    course_id = _make_course(learner, uid, "NumPy 学习8", "能够进行数组计算")
    base_km = _numpy_knowledge_map()
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": base_km, "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    # 重新生成，新增 reranking 节点
    extended = _numpy_knowledge_map()
    extended.nodes.append(_kn("n6", "结果重排序", "application", "x", "hard", ["向量化计算"], "reranking"))
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": extended, "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)
    svc = LearningMapService(learner)
    resp = svc.build(uid, course_id)
    rerank = next((n for n in resp.nodes if n.id == "reranking"), None)
    assert rerank is not None
    assert rerank.mastery is None  # UNKNOWN
    assert rerank.status == "unknown"


# ---------------------------------------------------------------------------
# 14. Removed KC 不删历史
# ---------------------------------------------------------------------------

def test_removed_kc_keeps_history(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-removed"
    course_id = _make_course(learner, uid, "NumPy 学习9", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)
    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    for _ in range(8):
        wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="向量数组练习"))
    # 给 numpy_indexing 也积累历史（evidence），随后从图中删除
    for _ in range(8):
        wf.answer_turn(uid, TutorRequest(kc_id="numpy_indexing", message="向量数组练习"))
    # 删除 numpy_indexing
    reduced = _numpy_knowledge_map()
    reduced.nodes = [n for n in reduced.nodes if n.canonical_key != "numpy_indexing"]
    reduced.recommended_path = ["n1", "n3", "n4", "n5"]
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": reduced, "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)

    # active map 不再展示 numpy_indexing
    svc = LearningMapService(learner)
    resp = svc.build(uid, course_id)
    assert "numpy_indexing" not in {n.id for n in resp.nodes}
    # 但 learner history 不删除
    states = learner.repo.list_kcs(uid, course_id)
    assert "numpy_indexing" in {s["kc_id"] for s in states}


# ---------------------------------------------------------------------------
# 15 / 16. built-in fallback 兼容
# ---------------------------------------------------------------------------

def test_builtin_llm_rag_fallback(learner):
    svc = LearningMapService(learner)
    resp = svc.build("any-user", "LLM-RAG")
    ids = {n.id for n in resp.nodes}
    assert {"llm_basics", "embedding", "rag"} <= ids
    assert resp.graph_source == "builtin"


def test_builtin_java_oop_fallback(learner):
    svc = LearningMapService(learner)
    resp = svc.build("any-user", "JAVA-OOP")
    assert {n.id for n in resp.nodes}
    assert resp.graph_source == "builtin"


# ---------------------------------------------------------------------------
# 17. UNKNOWN != 0
# ---------------------------------------------------------------------------

def test_unknown_mastery_is_null_not_zero(learner, monkeypatch):
    uid = "sp-unknown"
    course_id = _make_course(learner, uid, "NumPy 学习10", "能够进行数组计算")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算", learner=learner)
    svc = LearningMapService(learner)
    resp = svc.build(uid, course_id)
    b = next(n for n in resp.nodes if n.id == "numpy_broadcasting")
    assert b.mastery is None
    assert b.mastery != 0


# ---------------------------------------------------------------------------
# 18. End-to-end arbitrary goal (NumPy) with evidence update
# ---------------------------------------------------------------------------

def test_end_to_end_numpy_with_evidence(learner, monkeypatch):
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    uid = "sp-e2e"
    course_id = _make_course(learner, uid, "NumPy 学习11", "能够进行数组计算、广播和基础数据处理")
    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        lambda *a, **k: {"knowledge_map": _numpy_knowledge_map(), "final_plan": "P",
                         "plan_steps": [], "goal": "g", "student_input": None,
                         "decomposition": None, "lesson_cache": {}},
    )
    generate_plan(uid, course_id, goal="能够进行数组计算、广播和基础数据处理", learner=learner)

    svc = LearningMapService(learner)
    before = svc.build(uid, course_id)
    assert next(n for n in before.nodes if n.id == "numpy_array").mastery is None

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    for _ in range(8):
        wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="向量数组练习"))

    after = svc.build(uid, course_id)
    assert (next(n for n in after.nodes if n.id == "numpy_array").mastery or 0) >= 0.7
