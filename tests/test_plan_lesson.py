"""学习计划 Lesson 懒生成 / 计划设置持久化 / 课程解析器 token 边界 / 计划归属防 ghost-state。

使用 TestClient + 临时 DB；Lesson 的 LLM 调用通过 monkeypatch 替换，避免真实网络。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edu_agent.adaptive.course_resolver import resolve_course_id  # noqa: E402
from edu_agent.api.main import app  # noqa: E402
from edu_agent.config.settings import get_settings  # noqa: E402
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "lm.db")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", db)
    monkeypatch.setenv("LEARNER_MODEL_USER_ID", "STU-LESSON")
    get_settings.cache_clear()
    LearnerModelService._shared_default = None
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 离线 mock 计划生成工作流：避免真实 LLM 网络调用（7 个 agent 步骤）。
# 本文件只验证 lesson/plan 的行为（缓存 / 归属 / 配置 / mastery），
# 不依赖计划正文内容，故用确定性假数据替代 run_study_plan_workflow。
# ---------------------------------------------------------------------------


class _FakeNode:
    def __init__(self, **kw):
        self._d = kw

    def model_dump(self):
        return self._d


class _FakeKnowledgeMap:
    def __init__(self, nodes):
        self.nodes = nodes


@pytest.fixture(autouse=True)
def mock_plan_workflow(monkeypatch):
    def fake_workflow(*args, **kwargs):
        nodes = [
            _FakeNode(
                id="KC1",
                title="变量与类型",
                summary="认识变量与基本类型",
                learning_objective="能定义并使用变量",
                prerequisites=[],
                stage_id="stage-1",
                stage_title="基础准备",
                stage_order=1,
                difficulty="easy",
                estimated_minutes=30,
            ),
            _FakeNode(
                id="KC2",
                title="控制流",
                summary="条件判断与循环",
                learning_objective="能编写循环与分支",
                prerequisites=["KC1"],
                stage_id="stage-2",
                stage_title="核心学习",
                stage_order=2,
                difficulty="medium",
                estimated_minutes=45,
            ),
        ]
        return {
            "final_plan": "## 学习计划\n1. 变量与类型\n2. 控制流",
            "knowledge_map": _FakeKnowledgeMap(nodes),
            "analysis": {},
            "decomposition": {},
            "research": {},
            "evaluated_research": {},
            "draft_plan": {},
            "validation": {},
            "review": {"review_summary": "ok"},
        }

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service.run_study_plan_workflow",
        fake_workflow,
    )


# ---------------------------------------------------------------------------
# 课程解析器：token/word boundary（修复 "javascript" 误命中 "java"）
# ---------------------------------------------------------------------------


def test_resolver_token_boundary():
    assert resolve_course_id("Java") == "JAVA-OOP"
    assert resolve_course_id("Java OOP") == "JAVA-OOP"
    assert resolve_course_id("java oop") == "JAVA-OOP"
    # 关键回归：javascript 不应命中 java
    assert resolve_course_id("JavaScript 入门").startswith("CUSTOM-")
    assert resolve_course_id("JavaScript 和 React").startswith("CUSTOM-")
    assert resolve_course_id("Transformer") == "TRANSFORMER"
    assert resolve_course_id("注意力机制") == "TRANSFORMER"


# ---------------------------------------------------------------------------
# Plan Step Lesson：GET-OR-GENERATE（懒生成 + 缓存）
# ---------------------------------------------------------------------------


def test_lesson_generate_then_cache(client, monkeypatch):
    calls = {"n": 0}

    def fake_generate_lesson_markdown(step, context_text):
        calls["n"] += 1
        return "## 本节要学什么\n这是讲解内容。"

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service._generate_lesson_markdown",
        fake_generate_lesson_markdown,
    )

    r = client.post("/api/courses", json={"topic": "Python 数据分析", "goal": "两周完成报告"})
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 14, "daily_minutes": 60},
    )
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]

    # 首次调用：生成
    r = client.post(f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["step_id"] == step["step_id"]
    assert body["lesson_markdown"].startswith("## 本节要学什么")
    assert body["lesson_generated_at"]
    assert body["title"] == step["title"]
    assert calls["n"] == 1

    # 第二次调用：命中缓存，不再调 LLM
    r = client.post(f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson")
    assert r.status_code == 200, r.text
    assert calls["n"] == 1

    # 落库：get_plan 返回的 step 携带 lesson_markdown
    plan = client.get(f"/api/courses/{cid}/plan").json()
    persisted = next(s for s in plan["steps"] if s["step_id"] == step["step_id"])
    assert persisted["lesson_markdown"].startswith("## 本节要学什么")
    assert persisted["lesson_generated_at"]


def test_lesson_ownership_404(client):
    # 创建课程 + 生成计划都用同一 owner USER-A（不依赖 fixture 默认 owner）
    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200
    step = r.json()["steps"][0]

    # 非 owner（USER-B）访问他人 step 的 lesson → 404
    r = client.post(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson",
        headers={"X-User-Id": "USER-B"},
    )
    assert r.status_code == 404

    # 不存在的 step → 404（owner USER-A）
    r = client.post(
        f"/api/courses/{cid}/plan/steps/STEP-NOPE/lesson",
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Lesson 个性化使用课程保存的周期/每日时长（与 Plan 生成同一配置，绝不 14/60）
# ---------------------------------------------------------------------------


def test_lesson_uses_course_settings(client, monkeypatch):
    import edu_agent.application.study_plan_service as sps

    captured = {}
    orig_pc = sps.build_plan_context

    def spy_pc(*args, **kwargs):
        captured.update(kwargs)
        return orig_pc(*args, **kwargs)

    monkeypatch.setattr(sps, "build_plan_context", spy_pc)

    def fake_gen(step, context_text):
        return "## 本节要学什么\n这是讲解内容。"

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service._generate_lesson_markdown",
        fake_gen,
    )

    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 30, "daily_minutes": 90},
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]

    r = client.post(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson",
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text
    # Lesson 个性化必须使用课程已保存的 30/90，绝不能 14/60
    assert captured.get("duration_days") == 30
    assert captured.get("daily_minutes") == 90
    assert captured.get("duration_days") != 14
    assert captured.get("daily_minutes") != 60


def test_lesson_does_not_change_mastery(client, monkeypatch):
    def fake_gen(step, context_text):
        return "## 本节要学什么\n这是讲解内容。"

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service._generate_lesson_markdown",
        fake_gen,
    )

    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    kc_id = step["kc_id"]

    learner = LearnerModelService()
    now = "2026-08-12T00:00:00Z"
    learner.repo.upsert_kc(
        {
            "user_id": "USER-A",
            "course_id": cid,
            "kc_id": kc_id,
            "mastery": 0.5,
            "confidence": 0.4,
            "status": "learning",
            "created_at": now,
            "updated_at": now,
        }
    )
    before = learner.repo.get_kc("USER-A", cid, kc_id)
    before_mastery = before.get("mastery") if before else None

    r = client.post(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson",
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text

    after = learner.repo.get_kc("USER-A", cid, kc_id)
    after_mastery = after.get("mastery") if after else None
    # 生成 Lesson 绝不修改 mastery（UNKNOWN=None 也不应变成 0）
    assert before_mastery == after_mastery


def test_lesson_timestamp_consistent_with_plan(client, monkeypatch):
    def fake_gen(step, context_text):
        return "## 本节要学什么\n这是讲解内容。"

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service._generate_lesson_markdown",
        fake_gen,
    )

    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]

    r = client.post(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson",
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text
    lesson_ts = r.json()["lesson_generated_at"]
    assert lesson_ts

    plan = client.get(f"/api/courses/{cid}/plan", headers={"X-User-Id": "USER-A"}).json()
    persisted = next(s for s in plan["steps"] if s["step_id"] == step["step_id"])
    # 响应时间戳必须与落库时间戳完全一致（单一 generated_at）
    assert persisted["lesson_generated_at"] == lesson_ts


def test_lesson_does_not_rollback_step_status(client, monkeypatch):
    # 模拟 Lesson 生成期间 step 被并发标记为 completed：
    # fake LLM 在返回前把 step 置为 completed（同一线程，避免跨线程 SQLite 锁竞争）。
    captured: dict = {}

    def gen_that_completes_step(step, context_text):
        from edu_agent.application.study_plan_service import update_step_status

        # step 初始为 in_progress（下方已置），此处模拟并发完成
        update_step_status("USER-A", cid, step["step_id"], "completed")
        captured["completed"] = True
        return "## 本节要学什么\n这是讲解内容。"

    monkeypatch.setattr(
        "edu_agent.application.study_plan_service._generate_lesson_markdown",
        gen_that_completes_step,
    )

    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    # 先把 step 设为 in_progress（模拟用户「开始学习」）
    r = client.patch(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}",
        json={"status": "in_progress"},
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text

    # 触发生成：fake 内部会把 step 置 completed，落库必须以重读后的 fresh(completed) 为基准，
    # 绝不能把 status 用最初 step snapshot 回滚成 in_progress / not_started。
    r = client.post(
        f"/api/courses/{cid}/plan/steps/{step['step_id']}/lesson",
        headers={"X-User-Id": "USER-A"},
    )
    assert r.status_code == 200, r.text
    assert captured.get("completed") is True

    plan = client.get(f"/api/courses/{cid}/plan", headers={"X-User-Id": "USER-A"}).json()
    persisted = next(s for s in plan["steps"] if s["step_id"] == step["step_id"])
    # 关键回归：status 必须为 completed（不被旧 snapshot 回滚）
    assert persisted["status"] == "completed"
    # lesson 已落地
    assert persisted["lesson_markdown"].startswith("## 本节要学什么")
    assert persisted["lesson_generated_at"]
    # progress 反映 completed（1 / 总步骤数）
    total = len(plan["steps"])
    assert plan["progress"] == round(1 / total, 3)
    # mastery 仍未改变（UNKNOWN 仍为 None）
    kc_id = step["kc_id"]
    kc = LearnerModelService().repo.get_kc("USER-A", cid, kc_id)
    assert kc is None or kc.get("mastery") is None


# ---------------------------------------------------------------------------
# 计划设置持久化：create_course 保存 / generate 解析 / 写回
# ---------------------------------------------------------------------------


def test_plan_settings_persistence(client):
    r = client.post(
        "/api/courses",
        json={"topic": "Python 数据分析", "duration_days": 21, "daily_minutes": 45},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["course_id"]

    course = client.get(f"/api/courses/{cid}").json()
    assert course["duration_days"] == 21
    assert course["daily_minutes"] == 45

    # 不显式传设置 → 沿用课程已保存的 21/45
    r = client.post(f"/api/courses/{cid}/plan/generate", json={})
    assert r.status_code == 200, r.text

    # 重新生成并显式覆盖 → 写回为新的默认值
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 30, "daily_minutes": 90},
    )
    assert r.status_code == 200, r.text
    course = client.get(f"/api/courses/{cid}").json()
    assert course["duration_days"] == 30
    assert course["daily_minutes"] == 90


# ---------------------------------------------------------------------------
# 计划归属：owner 校验优先，避免非法 course_id 产生 ghost learner_course_state
# ---------------------------------------------------------------------------


def test_plan_ownership_no_ghost_state(client):
    r = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200
    cid = r.json()["course_id"]

    # USER-B 对他人课程生成计划 → 404（不创建 ghost state）
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-B"}
    )
    assert r.status_code == 404

    # USER-B 获取他人计划 → 404
    r = client.get(f"/api/courses/{cid}/plan", headers={"X-User-Id": "USER-B"})
    assert r.status_code == 404

    # USER-B 获取他人课程 → 404（确认无 ghost learner_course_state 行）
    r = client.get(f"/api/courses/{cid}", headers={"X-User-Id": "USER-B"})
    assert r.status_code == 404

    # USER-A 自身可正常生成
    r = client.post(
        f"/api/courses/{cid}/plan/generate", json={}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200
