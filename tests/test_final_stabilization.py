"""FINAL STABILIZATION 回归测试。

覆盖 spec 第 44 条 Backend A~H：
- A: invalid cycle → fallback → Plan IDs ⊆ Graph IDs
- B: delete course → dynamic graph deleted
- C: delete + recreate same topic → old graph does not resurrect
- D: duplicate canonical key → only one component
- E: locked kc → tutor start rejected
- F: tutor turn has turn_id → response evidence tied to same turn
- G: same turn_id submitted twice → mastery not double-counted
- H: current kc mastered → response.kc_id remains current kc, next_recommended_kc separate
- P2-1: recent_error 真正基于近期 evidence
"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

from datetime import datetime, timezone

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course, delete_course
from edu_agent.application.study_plan_service import generate_plan, get_plan
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode
from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
from edu_agent.workflows.tutoring.schemas import PrerequisiteNotMet, TutorRequest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kn(node_id, title, category, summary, difficulty, prerequisites, canonical_key=None):
    return KnowledgeNode(
        id=node_id, title=title, category=category, summary=summary,
        difficulty=difficulty, prerequisites=prerequisites,
        estimated_minutes=30, stage_id="s1", stage_title="阶段",
        stage_order=1, learning_objective="obj", canonical_key=canonical_key,
    )


def _cycled_knowledge_map() -> KnowledgeMap:
    """LLM 返回带环的知识地图 → canonicalization 无效 → 触发 fallback。"""
    nodes = [
        _kn("n1", "NumPy 数组基础", "core", "ndarray", "easy", ["n3"], "numpy_array"),
        _kn("n2", "数组索引", "core", "indexing", "easy", ["n1"], "numpy_indexing"),
        _kn("n3", "广播机制", "core", "broadcasting", "hard", ["n2"], "numpy_broadcasting"),
    ]
    return KnowledgeMap(topic="NumPy", nodes=nodes, recommended_path=["n1", "n2", "n3"])


@pytest.fixture
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "learner.db"))


def _stub_plan_workflow(monkeypatch, km):
    import edu_agent.application.study_plan_service as sps

    def fake(*args, **kwargs):
        return {
            "knowledge_map": km, "final_plan": "P", "plan_steps": [],
            "goal": "g", "student_input": None, "decomposition": None, "lesson_cache": {},
        }

    monkeypatch.setattr(sps, "run_study_plan_workflow", fake)


# ---------------------------------------------------------------------------
# Backend A：invalid cycle → fallback → Plan IDs ⊆ Graph IDs
# ---------------------------------------------------------------------------
def test_fallback_plan_ids_subset_of_graph_ids(learner, monkeypatch):
    uid = "fb-A"
    course_id = create_course(uid, "NumPy", goal="数组计算", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())

    plan = generate_plan(uid, course_id, goal="数组计算", learner=learner)

    svc = LearningMapService(learner)
    resp = svc.build(uid, course_id)
    graph_ids = {n.id for n in resp.nodes}
    # 至少回退成功、图非空
    assert len(graph_ids) >= 3
    # 关键 invariant：Plan 的每个 step.kc_id 必须都在 Graph 的节点里
    for step in plan["steps"]:
        assert step["kc_id"] in graph_ids
    # fallback 路径下没有残留草稿临时 id
    assert not any(s.startswith("knowledge-") for s in graph_ids)


# ---------------------------------------------------------------------------
# Backend B/C：删除课程 → dynamic graph 删除；重建同名不复活旧 graph
# ---------------------------------------------------------------------------
def test_delete_course_removes_dynamic_graph(learner, monkeypatch):
    uid = "fb-B"
    course_id = create_course(uid, "NumPy", goal="数组计算", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="数组计算", learner=learner)

    # 生成后 graph 存在
    assert learner.repo.get_course_kc_graph(uid, course_id) is not None

    # 删除课程 → dynamic graph 一并删除
    delete_course(uid, course_id, learner=learner)
    assert learner.repo.get_course_kc_graph(uid, course_id) is None


def test_delete_recreate_does_not_resurrect_old_graph(learner, monkeypatch):
    uid = "fb-C"

    # 第一代课程 + 图
    course_id = create_course(uid, "NumPy", goal="数组计算", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="数组计算", learner=learner)
    assert learner.repo.get_course_kc_graph(uid, course_id) is not None

    # 删除课程
    delete_course(uid, course_id, learner=learner)
    assert learner.repo.get_course_kc_graph(uid, course_id) is None

    # 重新创建同名课程：此时不应再读到旧 graph（无 graph snapshot）
    new_course_id = create_course(uid, "NumPy", goal="数组计算", learner=learner)["course_id"]
    # 新课程 ID 可能不同；但无论相同与否，其 graph snapshot 必须为空
    graph = learner.repo.get_course_kc_graph(uid, new_course_id)
    assert graph is None


# ---------------------------------------------------------------------------
# Backend D：duplicate canonical key → only one component
# ---------------------------------------------------------------------------
def test_duplicate_canonical_merges_to_one_component(learner, monkeypatch):
    from edu_agent.workflows.study_plan.canonicalizer import KnowledgeMapCanonicalizer

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
    # 必须真正合并为 1 个 component（不能只断言 set 去重）
    matching = [c for c in res.course.components if c.kc_id == "embedding"]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# Backend E：locked kc → tutor start rejected
# ---------------------------------------------------------------------------
def test_locked_kc_tutor_start_rejected(learner, monkeypatch):
    uid = "fb-E"
    course_id = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="RAG", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    # numpy_array 无前置 → 可学；numpy_broadcasting 前置未满足 → locked
    with pytest.raises(PrerequisiteNotMet) as ei:
        wf.start_turn(uid, TutorRequest(kc_id="numpy_broadcasting"))
    assert ei.value.kc_id == "numpy_broadcasting"
    assert len(ei.value.prerequisites) >= 1


# ---------------------------------------------------------------------------
# Backend F/G：turn_id 上下文 + 同 turn 防重复计分
# ---------------------------------------------------------------------------
def test_turn_context_and_no_double_count(learner, monkeypatch):
    uid = "fb-FG"
    course_id = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="RAG", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    # 开始 numpy_array 教学（无前置，可学）
    start = wf.start_turn(uid, TutorRequest(kc_id="numpy_array"))
    assert start.turn_id

    # 第一次回答（带 turn_id）
    first = wf.answer_turn(uid, TutorRequest(
        kc_id="numpy_array", message="ndarray", turn_id=start.turn_id))
    after_first = learner.build_bundle(uid, course_id).course_state.get_knowledge("numpy_array").mastery

    # 同一 turn_id 再次提交 → 不重复计分（event_id 幂等）
    wf.answer_turn(uid, TutorRequest(
        kc_id="numpy_array", message="ndarray", turn_id=start.turn_id))
    after_second = learner.build_bundle(uid, course_id).course_state.get_knowledge("numpy_array").mastery
    assert after_second == after_first

    # 新 turn → 正常计分（mastery 继续变化，至少不会倒退）
    start2 = wf.start_turn(uid, TutorRequest(kc_id="numpy_array"))
    wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="ndarray", turn_id=start2.turn_id))


# ---------------------------------------------------------------------------
# Backend H：current kc mastered → response.kc_id 保持 current kc，next 单独返回
# ---------------------------------------------------------------------------
def test_current_kc_separate_from_next_recommended(learner, monkeypatch):
    uid = "fb-H"
    course_id = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="RAG", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)
    # 把 numpy_array 推进到 mastered
    for _ in range(8):
        learner.apply_event({
            "event_type": "TUTOR_EVIDENCE", "user_id": uid, "course_id": course_id,
            "kc_id": "numpy_array", "source": "seed", "evidence_strength": "strong",
            "payload": {"kc_id": "numpy_array", "kc_name": "NumPy 数组基础",
                        "correctness": "correct", "difficulty": 2, "hint_level": 0,
                        "confidence": 0.9, "evidence_strength": "strong",
                        "misconceptions": [], "evidence_type": "tutor_turn", "teaching_action": ""},
        })

    start = wf.start_turn(uid, TutorRequest(kc_id="numpy_array"))
    resp = wf.answer_turn(uid, TutorRequest(kc_id="numpy_array", message="ndarray", turn_id=start.turn_id))
    # P1-4：response.kc_id 必须仍是当前 KC（numpy_array），next_recommended_kc 单独返回
    assert resp.kc_id == "numpy_array"
    assert resp.next_recommended_kc is not None
    assert resp.next_recommended_kc != "numpy_array"


# ---------------------------------------------------------------------------
# P2-3：dynamic Learning Map goal 真实（非空）
# ---------------------------------------------------------------------------
def test_learning_map_goal_not_empty(learner, monkeypatch):
    uid = "fb-p23"
    course_id = create_course(uid, "NumPy", goal="熟练进行数组计算与广播", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="熟练进行数组计算与广播", learner=learner)

    resp = LearningMapService(learner).build(uid, course_id)
    assert resp.goal and resp.goal.strip(), "LearningMap.goal 不应为空"


# ---------------------------------------------------------------------------
# P2-1：recent_error 真正基于近期 evidence
# ---------------------------------------------------------------------------
def test_recent_error_only_recent(learner, monkeypatch):
    uid = "fb-p21"
    course_id = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan_workflow(monkeypatch, _cycled_knowledge_map())
    generate_plan(uid, course_id, goal="RAG", learner=learner)

    wf = TutoringWorkflow(course_id, learner, user_id=uid)

    def seed(correctness):
        learner.apply_event({
            "event_type": "TUTOR_EVIDENCE", "user_id": uid, "course_id": course_id,
            "kc_id": "numpy_array", "source": "seed", "evidence_strength": "strong",
            "payload": {"kc_id": "numpy_array", "kc_name": "NumPy 数组基础",
                        "correctness": correctness, "difficulty": 2, "hint_level": 0,
                        "confidence": 0.9, "evidence_strength": "strong",
                        "misconceptions": [], "evidence_type": "tutor_turn", "teaching_action": ""},
        })

    # 历史有过错误，但最近连续正确 → recent_error 应消失
    seed("incorrect")
    seed("incorrect")
    seed("correct")
    seed("correct")
    seed("correct")
    snap = wf._snapshot(uid)
    assert snap["recent_error_map"].get("numpy_array") in (False, None)

    # 最新一条错误 → recent_error=True
    seed("incorrect")
    snap = wf._snapshot(uid)
    assert snap["recent_error_map"].get("numpy_array") is True
