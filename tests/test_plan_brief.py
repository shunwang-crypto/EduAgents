"""PlanBrief 测试：goal/known skills/skill gaps/critical path 正确，不发明不存在的 KC。"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.plan_brief_service import PlanBriefService
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.learner_model import db


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

    def kn(node_id, title, prereqs=(), difficulty="easy"):
        return KnowledgeNode(
            id=node_id, title=title, category="core", summary=f"{title} 描述",
            prerequisites=list(prereqs), difficulty=difficulty,
            estimated_minutes=30, stage_id="s1", stage_title="基础准备",
            stage_order=1, canonical_key=node_id,
            learning_objective=f"掌握 {title}",
        )

    return KnowledgeMap(
        topic="LLM",
        nodes=[
            kn("llm_api", "LLM API 调用"),
            kn("prompt", "Prompt 基础", ["llm_api"]),
            kn("embedding", "Embedding", ["prompt"]),
        ],
        recommended_path=["llm_api", "prompt", "embedding"],
    )


def test_plan_brief_goal_and_stages(learner, monkeypatch, km):
    uid = "pb-1"
    cid = create_course(uid, "LLM", goal="独立开发 RAG 应用", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    plan = generate_plan(uid, cid, goal="独立开发 RAG 应用", learner=learner)
    brief = PlanBriefService(learner).get(uid, cid)

    assert brief["plan_id"] == plan["plan_id"]
    assert brief["course_id"] == cid
    assert "RAG" in brief["goal"]
    assert len(brief["stage_overview"]) >= 1
    # 不发明不存在的 KC：critical path 必须是 graph 中真实节点
    map_resp = LearningMapService(learner).build(uid, cid)
    graph_ids = {n.id for n in map_resp.nodes}
    path_ids = [p["kc_id"] for p in brief["critical_path"]]
    assert set(path_ids).issubset(graph_ids)
    # critical path 的人类名称非空，且不使用内部 id 作为显示名
    for p in brief["critical_path"]:
        assert p["name"].strip()
        assert p["name"] != p["kc_id"]
    # 全部 skill 名来自 graph 节点
    all_titles = {n.name for n in map_resp.nodes}
    for s in brief["known_skills"] + brief["skill_gaps"]:
        assert s in all_titles


def test_plan_brief_known_skills_from_mastery(learner, monkeypatch, km):
    uid = "pb-2"
    cid = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    generate_plan(uid, cid, goal="RAG", learner=learner)

    # 把 llm_api 推进到 mastered
    for _ in range(6):
        learner.apply_event({
            "event_type": "TUTOR_EVIDENCE", "user_id": uid, "course_id": cid,
            "kc_id": "llm_api", "source": "seed", "evidence_strength": "strong",
            "payload": {"kc_id": "llm_api", "correctness": "correct", "difficulty": 2,
                        "hint_level": 0, "confidence": 0.9, "evidence_strength": "strong",
                        "misconceptions": [], "evidence_type": "tutor_turn", "teaching_action": ""},
        })

    brief = PlanBriefService(learner).get(uid, cid)
    assert any("LLM API" in s for s in brief["known_skills"])


def test_plan_brief_no_plan_raises(learner):
    uid = "pb-3"
    cid = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    with pytest.raises(KeyError):
        PlanBriefService(learner).get(uid, cid)


def test_plan_brief_unknown_not_skill_gap(learner, monkeypatch, km):
    """§56：所有 KC mastery=None → known_skills=[]、skill_gaps=[]、unassessed 非空。"""
    uid = "pb-4"
    cid = create_course(uid, "LLM", goal="RAG", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    generate_plan(uid, cid, goal="RAG", learner=learner)

    brief = PlanBriefService(learner).get(uid, cid)
    # UNKNOWN 不允许进入 known / skill_gaps
    assert brief["known_skills"] == []
    assert brief["skill_gaps"] == []
    assert len(brief["unassessed_skills"]) > 0
    # 全部组件都在 unassessed
    graph_ids = {n.id for n in LearningMapService(learner).build(uid, cid).nodes}
    assert len(brief["unassessed_skills"]) == len(graph_ids)


def test_old_db_migrates_plan_brief_json_column(tmp_path):
    """§：旧库（无 plan_brief_json 列）init_db 后自动补列，避免 backfill 报 no such column。"""
    import sqlite3

    old_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(old_path)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS study_plans ("
        "plan_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,"
        "goal_id TEXT DEFAULT '', title TEXT DEFAULT '', summary TEXT DEFAULT '',"
        "plan_markdown TEXT NOT NULL, progress REAL DEFAULT 0.0,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
        "UNIQUE (user_id, course_id));"
    )
    conn.commit()
    conn.close()

    c = db.connect(old_path)
    db.init_db(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(study_plans)").fetchall()}
    c.close()
    assert "plan_brief_json" in cols

    # 迁移后可通过 LearnerModelService 正常读写（不再抛 no such column）
    lm = LearnerModelService(db_path=old_path)
    lm.repo.update_plan_brief("P1", "{}")
