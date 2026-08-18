"""PlanBrief 测试：goal/known skills/skill gaps/critical path 正确，不发明不存在的 KC。"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.plan_brief_service import PlanBriefService
from edu_agent.application.learning_map_service import LearningMapService


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
    assert set(brief["critical_path"]).issubset(graph_ids)
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
