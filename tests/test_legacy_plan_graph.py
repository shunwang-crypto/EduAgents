"""Legacy Plan → Graph 恢复测试（旧课程有 Plan、无 Graph）。"""

import os

os.environ.setdefault("EDU_OFFLINE", "1")

import pytest

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.application.course_service import create_course
from edu_agent.application.study_plan_service import generate_plan
from edu_agent.application.learning_map_service import LearningMapService
from edu_agent.application.course_graph_service import CourseGraphService


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


@pytest.fixture
def km():
    from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode

    def kn(node_id, title, prereqs=()):
        return KnowledgeNode(
            id=node_id, title=title, category="core", summary=f"{title}",
            prerequisites=list(prereqs), difficulty="easy", estimated_minutes=30,
            stage_id="s1", stage_title="基础准备", stage_order=1,
            canonical_key=node_id,
            learning_objective=f"掌握 {title}",
        )

    return KnowledgeMap(
        topic="LLM",
        nodes=[
            kn("llm_api", "LLM API"),
            kn("prompt", "Prompt", ["llm_api"]),
            kn("embedding", "Embedding", ["prompt"]),
        ],
        recommended_path=["llm_api", "prompt", "embedding"],
    )


def test_legacy_plan_without_graph_recovers(learner, monkeypatch, km):
    # 使用无内置 course 的自定义主题，避免 load_active_graph 命中 builtin LLM-RAG
    uid = "legacy-1"
    cid = create_course(uid, "Legacy主题", goal="掌握自定义主题", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    plan = generate_plan(uid, cid, goal="掌握自定义主题", learner=learner)

    # 模拟旧库状态：删除动态 graph（保留 Plan）
    learner.repo.delete_course_kc_graph(uid, cid)
    assert learner.repo.get_course_kc_graph(uid, cid) is None

    # LearningMap 应能恢复，而不是报「无计划」
    svc = LearningMapService(learner)
    resp = svc.build(uid, cid)
    graph_ids = {n.id for n in resp.nodes}
    assert "llm_api" in graph_ids
    assert "embedding" in graph_ids
    # 自动 migrate 成功 → 现在有动态 graph
    assert learner.repo.get_course_kc_graph(uid, cid) is not None


def test_legacy_plan_unrecoverable_reports_upgrade_needed(learner, monkeypatch, km):
    """Plan 存在但 steps 无法安全恢复（kc_id 为空）→ recovery 返回 None（不误导「无计划」）。"""
    uid = "legacy-2"
    cid = create_course(uid, "Legacy主题2", goal="掌握", learner=learner)["course_id"]
    _stub_plan(monkeypatch, km)
    plan = generate_plan(uid, cid, goal="掌握", learner=learner)
    learner.repo.delete_course_kc_graph(uid, cid)
    # 直接构造「kc_id 为空」的步骤，验证 recovery 不误判为「无计划」
    gs = CourseGraphService(learner._repo)
    assert gs.try_recover_from_plan(uid, cid, display_name="Legacy主题2") is not None
    # 当所有步骤 kc_id 都为空时 → 无法恢复
    for s in plan["steps"]:
        row = learner.repo.get_plan_step(plan["plan_id"], s["step_id"]) or {}
        row = dict(row)
        row["kc_id"] = ""
        learner.repo.upsert_plan_step(row)
    assert gs.try_recover_from_plan(uid, cid, display_name="Legacy主题2") is None
