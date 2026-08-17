"""Multi-Agent Adaptive Intelligent Tutoring System 后端测试。

覆盖 Phase 2-5 + 集成闭环。conftest 已强制离线，LLM 调用走确定性降级。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edu_agent.api.main import app  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402
from edu_agent.config.settings import get_settings  # noqa: E402

USER = "STU-ADAPTIVE"

OFFLINE_KEYS = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "XINGCHEN_API_KEY", "XINGCHEN_BASE_URL", "XINGCHEN_MODEL",
    "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_BASE_URL", "OPENCODE_ZEN_MODEL",
    "TAVILY_API_KEY",
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "lm.db")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", db)
    monkeypatch.setenv("LEARNER_MODEL_USER_ID", USER)
    for key in OFFLINE_KEYS:
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    LearnerModelService._shared_default = None
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    LearnerModelService._shared_default = None


# ---------------------------------------------------------------------------
# Phase 2: KC Graph
# ---------------------------------------------------------------------------


def test_llm_rag_is_dag():
    from edu_agent.domain.learning.kc_graph import get_course, is_dag

    c = get_course("LLM-RAG")
    assert c is not None
    assert is_dag(c) is True


def test_llm_rag_prerequisites():
    from edu_agent.domain.learning.kc_graph import get_course

    c = get_course("LLM-RAG")
    assert c.prerequisites("rag") == ["prompt", "vector_db"]
    assert c.prerequisites("vector_db") == ["embedding"]
    assert c.prerequisites("agent") == ["tool_calling"]
    assert c.prerequisites("embedding") == ["llm_basics"]


def test_llm_rag_topological_legality():
    from edu_agent.domain.learning.kc_graph import get_course

    c = get_course("LLM-RAG")
    pos = {kc.kc_id: i for i, kc in enumerate(c.components)}
    for r in c.relations:
        if r.relation == "prerequisite":
            assert pos[r.from_kc] < pos[r.to_kc], f"{r.from_kc} 应在 {r.to_kc} 之前"


def test_course_resolver_maps_keywords():
    from edu_agent.adaptive.course_resolver import resolve_course_id

    assert resolve_course_id("我想学大语言模型") == "LLM-RAG"
    assert resolve_course_id("RAG") == "LLM-RAG"
    assert resolve_course_id("Agent 智能体") == "LLM-RAG"
    assert resolve_course_id("java oop") == "JAVA-OOP"


# ---------------------------------------------------------------------------
# Phase 3: UNKNOWN != 0
# ---------------------------------------------------------------------------


def test_unknown_mastery_is_null(client):
    r = client.get(f"/api/courses/LLM-RAG/learning-map",
                   headers={"X-User-Id": USER})
    assert r.status_code == 200, r.text
    data = r.json()
    embedding = next(n for n in data["nodes"] if n["id"] == "embedding")
    assert embedding["mastery"] is None
    assert embedding["status"] == "unknown"


# ---------------------------------------------------------------------------
# Phase 3/5: Locked
# ---------------------------------------------------------------------------


def test_locked_when_prereq_weak():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy

    c = get_course("LLM-RAG")
    pol = HeuristicAdaptivePolicy(c, goal_kcs=[k.kc_id for k in c.components])
    mm = {"embedding": 0.35}  # weak 前置 → vector_db 锁定
    assert pol.is_locked("vector_db", mm) is True


def test_locked_when_prereq_unknown():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy

    c = get_course("LLM-RAG")
    pol = HeuristicAdaptivePolicy(c, goal_kcs=[k.kc_id for k in c.components])
    mm = {"embedding": None}
    assert pol.is_locked("vector_db", mm) is True


def test_unlock_when_prereq_mastered():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy

    c = get_course("LLM-RAG")
    pol = HeuristicAdaptivePolicy(c, goal_kcs=[k.kc_id for k in c.components])
    mm = {"embedding": 0.74}  # 达到阈值 → vector_db 解锁
    assert pol.is_locked("vector_db", mm) is False


# ---------------------------------------------------------------------------
# Phase 4/5: Planner
# ---------------------------------------------------------------------------


def test_planner_recommends_embedding_not_rag():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy

    c = get_course("LLM-RAG")
    pol = HeuristicAdaptivePolicy(c, goal_kcs=[k.kc_id for k in c.components])
    # 验收场景初始状态：llm_basics/prompt 已掌握，embedding 未知
    mm = {"llm_basics": 0.9, "prompt": 0.85, "embedding": 0.35, "vector_db": None, "rag": None}
    path = pol.recommended_path(mm)
    assert path[0] == "embedding"
    assert "rag" not in path or path.index("rag") > path.index("embedding")


def test_planner_decision_structure():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.workflows.tutoring.agents import Planner

    c = get_course("LLM-RAG")
    planner = Planner(c, goal_kcs=[k.kc_id for k in c.components])
    mm = {"llm_basics": 0.9, "prompt": 0.85, "embedding": None, "vector_db": None, "rag": None}
    d = planner.plan(mm)
    assert d.selected_kc == "embedding"
    assert "UNKNOWN_STATE" in d.reason_codes or "LOW_MASTERY" in d.reason_codes
    assert "PREREQUISITE_FOR_GOAL" in d.reason_codes


# ---------------------------------------------------------------------------
# Phase 4: Teaching Strategy
# ---------------------------------------------------------------------------


def test_strategy_unknown_assess():
    from edu_agent.workflows.tutoring.strategy import decide_action
    from edu_agent.workflows.tutoring.schemas import TeachingAction

    assert decide_action(None) == TeachingAction.ASSESS


def test_strategy_misconception_probe_or_compare():
    from edu_agent.workflows.tutoring.strategy import decide_action
    from edu_agent.workflows.tutoring.schemas import TeachingAction

    a = decide_action(0.5, misconceptions=["x"])
    assert a in (TeachingAction.PROBE, TeachingAction.COMPARE)


def test_strategy_mastered_challenge():
    from edu_agent.workflows.tutoring.strategy import decide_action
    from edu_agent.workflows.tutoring.schemas import TeachingAction

    assert decide_action(0.85) == TeachingAction.CHALLENGE


# ---------------------------------------------------------------------------
# Phase 4: Evidence → mastery update
# ---------------------------------------------------------------------------


def test_evidence_updates_mastery():
    from edu_agent.domain.learning.kc_graph import get_course
    from edu_agent.learner_model.service import LearnerModelService
    from edu_agent.workflows.tutoring.workflow import TutoringWorkflow
    from edu_agent.workflows.tutoring.schemas import TutorRequest

    db = ":memory:"
    lm = LearnerModelService(db_path=db)
    wf = TutoringWorkflow("LLM-RAG", lm)
    # 第一次：answer 正确 → mastery 从 None 变为 > 0
    resp = wf.answer_turn(USER, TutorRequest(kc_id="embedding",
                                              message="语义接近的向量距离更近"))
    snap = lm.build_bundle(USER, "LLM-RAG")
    item = snap.course_state.get_knowledge("embedding")
    assert item is not None
    assert item.mastery is not None
    assert item.mastery > 0.0


# ---------------------------------------------------------------------------
# Phase 5: Dynamic unlock via integration
# ---------------------------------------------------------------------------


def test_integration_learning_map_refreshes(client, monkeypatch, tmp_path):
    import os

    # 验收场景初始状态：llm_basics/prompt 已掌握（mastery>=0.7），embedding 未知
    db = os.environ.get("LEARNER_MODEL_DB_PATH")
    from edu_agent.learner_model.service import LearnerModelService

    seed = LearnerModelService(db_path=db)
    for kc_id in ("llm_basics", "prompt"):
        for _ in range(8):
            seed.apply_event({
                "event_type": "TUTOR_EVIDENCE", "user_id": USER, "course_id": "LLM-RAG",
                "kc_id": kc_id, "source": "seed",
                "payload": {"kc_id": kc_id, "correctness": "correct", "difficulty": 2,
                            "hint_level": 0, "confidence": 0.9, "misconceptions": [],
                            "evidence_type": "seed", "teaching_action": ""},
            })

    # 初始：embedding unknown
    r0 = client.get(f"/api/courses/LLM-RAG/learning-map",
                    headers={"X-User-Id": USER})
    assert r0.status_code == 200
    n0 = next(n for n in r0.json()["nodes"] if n["id"] == "embedding")
    assert n0["mastery"] is None
    assert n0["recommended"] is True

    # Tutor turn：回答 embedding 问题
    r1 = client.post(f"/api/courses/LLM-RAG/tutor/turn",
                     headers={"X-User-Id": USER},
                     json={"kc_id": "embedding",
                           "message": "语义接近的句子向量距离更近"})
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["kc_id"] == "embedding"
    assert body["teaching_action"]  # 有动作 badge

    # 再次拉取 learning map：mastery 应变化，且不为 0
    r2 = client.get(f"/api/courses/LLM-RAG/learning-map",
                    headers={"X-User-Id": USER})
    assert r2.status_code == 200
    n2 = next(n for n in r2.json()["nodes"] if n["id"] == "embedding")
    assert n2["mastery"] is not None
    assert n2["mastery"] > 0.0
    assert r2.json()["learning_map_changed"] if "learning_map_changed" in r2.json() else True


# ---------------------------------------------------------------------------
# 验收 Scenario：完整闭环 + 动态解锁
# ---------------------------------------------------------------------------


def test_acceptance_scenario_full_loop(client, monkeypatch, tmp_path):
    """Embedding UNKNOWN → ASSESS → Evidence → mastery update
    → Learning Map update → Vector DB unlock。"""
    import os

    db = os.environ.get("LEARNER_MODEL_DB_PATH")
    from edu_agent.learner_model.service import LearnerModelService

    seed = LearnerModelService(db_path=db)
    # 初始状态：llm_basics/prompt mastered，其余 unknown
    for kc_id in ("llm_basics", "prompt"):
        for _ in range(8):
            seed.apply_event({
                "event_type": "TUTOR_EVIDENCE", "user_id": USER, "course_id": "LLM-RAG",
                "kc_id": kc_id, "source": "seed",
                "payload": {"kc_id": kc_id, "correctness": "correct", "difficulty": 2,
                            "hint_level": 0, "confidence": 0.9, "misconceptions": [],
                            "evidence_type": "seed", "teaching_action": ""},
            })

    # 1) 初始 map：embedding recommended，vector_db locked
    r0 = client.get("/api/courses/LLM-RAG/learning-map", headers={"X-User-Id": USER}).json()
    emb0 = next(n for n in r0["nodes"] if n["id"] == "embedding")
    vec0 = next(n for n in r0["nodes"] if n["id"] == "vector_db")
    assert emb0["mastery"] is None and emb0["status"] == "unknown"
    assert emb0["recommended"] is True
    assert vec0["locked"] is True

    # 2) 开始 embedding 教学：应为 ASSESS
    r1 = client.post("/api/courses/LLM-RAG/tutor/turn",
                     headers={"X-User-Id": USER},
                     json={"kc_id": "embedding", "message": None}).json()
    assert r1["teaching_action"] == "ASSESS"

    # 3) 用户回答正确 → Evidence → mastery 上升
    r2 = client.post("/api/courses/LLM-RAG/tutor/turn",
                     headers={"X-User-Id": USER},
                     json={"kc_id": "embedding",
                           "message": "语义接近的句子 embedding 距离更近"}).json()
    assert r2["learner_state_changed"] is True

    # 4) 继续多轮答对，推进到 >= 0.7 以解锁 vector_db
    for _ in range(6):
        client.post("/api/courses/LLM-RAG/tutor/turn",
                    headers={"X-User-Id": USER},
                    json={"kc_id": "embedding",
                          "message": "语义相似度用余弦距离度量"}).json()

    r3 = client.get("/api/courses/LLM-RAG/learning-map", headers={"X-User-Id": USER}).json()
    emb3 = next(n for n in r3["nodes"] if n["id"] == "embedding")
    vec3 = next(n for n in r3["nodes"] if n["id"] == "vector_db")
    assert emb3["mastery"] is not None
    assert emb3["mastery"] >= 0.7, f"embedding 应达到 mastered：{emb3['mastery']}"
    # 5) 动态解锁：vector_db 从 locked 变为 unlocked
    assert vec3["locked"] is False, "embedding mastered 后 vector_db 应解锁"
    assert "vector_db" in r3["recommended_path"] or vec3["recommended"] is True
