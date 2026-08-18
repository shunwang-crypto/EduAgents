"""Learning Map 推荐语义 / active_path / critical_path / goal KC 契约测试。

覆盖 spec：§26 active_path 真实路径、§28 goal KC 非全部、§29 PREREQUISITE_FOR_GOAL、
§42 critical_path 真实 DAG longest path、§56 UNKNOWN。
"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.application.plan_brief_service import PlanBriefService


def _stub_plan(monkeypatch, km):
    import edu_agent.application.study_plan_service as sps

    def fake(*args, **kwargs):
        return {"knowledge_map": km, "final_plan": "P", "plan_steps": [],
                "goal": "g", "student_input": None, "decomposition": None,
                "analysis": None, "lesson_cache": {}}

    monkeypatch.setattr(sps, "run_study_plan_workflow", fake)


@pytest.fixture
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "learner.db"))


def _make_km(nodes):
    """nodes: list of (id,title,prereqs,category,difficulty)"""
    from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode

    ks = []
    for (nid, title, pre, cat, diff) in nodes:
        ks.append(KnowledgeNode(
            id=nid, title=title, category=cat, summary=f"{title} 描述",
            prerequisites=list(pre), difficulty=diff, estimated_minutes=30,
            stage_id="s1", stage_title="基础准备", stage_order=1,
            canonical_key=nid, learning_objective=f"掌握 {title}",
        ))
    return KnowledgeMap(topic="T", nodes=ks, recommended_path=[n[0] for n in nodes])


def _setup(learner, monkeypatch, topic, nodes):
    km = _make_km(nodes)
    _stub_plan(monkeypatch, km)
    uid = f"rec-{topic}"
    cid = create_course(uid, topic, goal="掌握", learner=learner)["course_id"]
    generate_plan(uid, cid, goal="掌握", learner=learner)
    return uid, cid


def _seed(learner, uid, cid, kc, mastery=0.9):
    """用强证据把 kc 推到指定掌握度。"""
    count = 8 if mastery >= 0.8 else 3
    for _ in range(count):
        learner.apply_event({
            "event_type": "TUTOR_EVIDENCE", "user_id": uid, "course_id": cid,
            "kc_id": kc, "source": "seed", "evidence_strength": "strong",
            "payload": {"kc_id": kc, "correctness": "correct", "difficulty": 2,
                        "hint_level": 0, "confidence": 0.9, "evidence_strength": "strong",
                        "misconceptions": [], "evidence_type": "tutor_turn", "teaching_action": ""},
        })


def test_current_recommended_single(learner, monkeypatch):
    """§24：current_recommended_kc 最多一个。"""
    uid, cid = _setup(learner, monkeypatch, "T1", [
        ("A", "基础A", [], "code", "easy"),
        ("B", "中间B", ["A"], "code", "easy"),
        ("C", "目标C", ["B"], "code", "hard"),
    ])
    m = LearningMapService(learner).build(uid, cid)
    rec_count = sum(1 for n in m.nodes if n.recommended)
    assert rec_count <= 1
    if m.current_recommended_kc:
        current = next(n for n in m.nodes if n.id == m.current_recommended_kc)
        assert current.recommended is True
        assert m.current_recommended_kc == m.active_path[0] if m.active_path else True


def test_active_path_is_real_dag_path(learner, monkeypatch):
    """§26/§58：active_path 相邻节点必须有 prerequisite edge。"""
    uid, cid = _setup(learner, monkeypatch, "T2", [
        ("A", "基础A", [], "code", "easy"),
        ("B", "中间B", ["A"], "code", "easy"),
        ("C", "目标C", ["A"], "code", "hard"),
        ("D", "末端D", ["B", "C"], "code", "hard"),
    ])
    # 掌握 A 后，active_path 应从 B 或 C 出发，不能出现 A→(无边的)节点跳跃
    _seed(learner, uid, cid, "A")
    m = LearningMapService(learner).build(uid, cid)
    edges = {(e.source, e.target) for e in m.edges}
    path = m.active_path
    for i in range(len(path) - 1):
        assert (path[i], path[i + 1]) in edges, f"no edge {path[i]}->{path[i+1]}"


def test_critical_path_is_longest_dag_path(learner, monkeypatch):
    """§42/§59：critical path 是真实最长依赖链，非 topological tail。"""
    uid, cid = _setup(learner, monkeypatch, "T3", [
        ("A", "A", [], "code", "easy"),
        ("B", "B", ["A"], "code", "easy"),
        ("C", "C", ["B"], "code", "easy"),
        ("D", "D", ["C"], "code", "hard"),
        ("E", "E", [], "code", "easy"),
        ("F", "F", ["E"], "code", "easy"),
    ])
    brief = PlanBriefService(learner).get(uid, cid)
    m = LearningMapService(learner).build(uid, cid)
    name_of = {n.id: n.name for n in m.nodes}
    path_names = [name_of[p["kc_id"]] for p in brief["critical_path"]]
    # 最长链是 A->B->C->D（长度 4），不是拓扑尾部
    assert path_names[:4] == ["A", "B", "C", "D"]
    assert len(path_names) >= 4
    # 关键路径人类名称不可为空、不可显示内部 id
    for p in brief["critical_path"]:
        assert p["name"].strip()
        assert p["name"] != p["kc_id"]


def test_prerequisite_for_goal_only_for_ancestors(learner, monkeypatch):
    """§29：只有真正 target 的 ancestor 才有 PREREQUISITE_FOR_GOAL，不能全部节点都有。"""
    uid, cid = _setup(learner, monkeypatch, "T4", [
        ("A", "基础A", [], "code", "easy"),
        ("B", "中间B", ["A"], "code", "easy"),
        ("C", "目标C", ["B"], "code", "hard"),
        ("X", "无关X", [], "code", "easy"),   # 孤立节点，非 target ancestor
    ])
    m = LearningMapService(learner).build(uid, cid)
    # 有相关 reason 的节点数 < 全部节点
    relevant = [n.id for n in m.nodes if "PREREQUISITE_FOR_GOAL" in n.reason_codes]
    assert len(relevant) < len(m.nodes), "不应所有节点都是 goal ancestor"
    # 孤立节点 X 不应有 PREREQUISITE_FOR_GOAL
    assert "X" not in relevant
