"""FastAPI 端到端测试（TestClient + tmp DB）。"""

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

USER = "STU-API"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 每个测试独立 DB
    db = str(tmp_path / "lm.db")
    monkeypatch.setenv("LEARNER_MODEL_DB_PATH", db)
    monkeypatch.setenv("LEARNER_MODEL_USER_ID", USER)

    # 测试环境显式 offline：清空所有外部 AI / search provider 配置，
    # 让 production workflow / ChatService 在无 provider 时立即走确定性降级，
    # 而非等待真实 LLM 网络 timeout（也确保有 .env 的开发机与无 .env 的 CI 行为一致）。
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "XINGCHEN_API_KEY",
        "XINGCHEN_BASE_URL",
        "XINGCHEN_MODEL",
        "OPENCODE_ZEN_API_KEY",
        "OPENCODE_ZEN_BASE_URL",
        "OPENCODE_ZEN_MODEL",
        "TAVILY_API_KEY",
    ):
        monkeypatch.setenv(key, "")

    # get_settings 是 lru_cache：清空缓存让上面的空配置生效
    get_settings.cache_clear()
    LearnerModelService._shared_default = None  # 重置共享实例
    with TestClient(app) as c:
        yield c

    # teardown：再次清缓存 + 重置共享实例，避免本测试的 offline 配置污染后续测试
    get_settings.cache_clear()
    LearnerModelService._shared_default = None


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_course_flow(client):
    # 创建课程
    r = client.post("/api/courses", json={"topic": "Python 数据分析", "goal": "两周完成数据分析"})
    assert r.status_code == 200, r.text
    course = r.json()
    assert course["course_id"].startswith("CUSTOM-")
    assert course["goal"]["name"] == "Python 数据分析"

    # 列表
    courses = client.get("/api/courses").json()
    assert len(courses) == 1

    # 获取/重命名（PATCH 字段：display_name，见 UpdateCourseRequest）
    cid = course["course_id"]
    assert client.get(f"/api/courses/{cid}").status_code == 200
    r = client.patch(f"/api/courses/{cid}", json={"display_name": "Python 数据分析进阶"})
    assert r.json()["display_name"] == "Python 数据分析进阶"

    # 生成计划（无 LLM 降级路径也能产出步骤）
    r = client.post(f"/api/courses/{cid}/plan/generate",
                    json={"goal": "两周完成数据分析", "duration_days": 14, "daily_minutes": 60})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["steps"]

    # 获取计划
    plan_get = client.get(f"/api/courses/{cid}/plan").json()
    assert plan_get["steps"]

    # 更新步骤状态 → progress 更新
    first = plan["steps"][0]
    r = client.patch(f"/api/courses/{cid}/plan/steps/{first['step_id']}",
                     json={"status": "completed"})
    assert r.status_code == 200
    assert r.json()["progress"] > 0.0

    # 删除课程
    assert client.delete(f"/api/courses/{cid}").status_code == 204
    assert client.get("/api/courses").json() == []


def test_duplicate_course_create_is_read_only(client):
    first = client.post(
        "/api/courses",
        json={"topic": "Python", "goal": "掌握 Python", "duration_days": 30, "daily_minutes": 90},
    )
    assert first.status_code == 200, first.text
    original = first.json()

    duplicate = client.post(
        "/api/courses",
        json={"topic": "Python", "goal": "", "duration_days": 14, "daily_minutes": 60},
    )
    assert duplicate.status_code == 200, duplicate.text
    current = duplicate.json()
    assert current["course_id"] == original["course_id"]
    assert current["display_name"] == original["display_name"]
    assert current["goal"]["target"] == "掌握 Python"
    assert current["duration_days"] == 30
    assert current["daily_minutes"] == 90


def test_duplicate_builtin_alias_create_preserves_course_configuration(client):
    category = client.post("/api/course-categories", json={"name": "后端"}).json()
    first = client.post(
        "/api/courses",
        json={"topic": "Java", "goal": "掌握 OOP", "category_id": category["category_id"],
              "duration_days": 30, "daily_minutes": 90},
    )
    assert first.status_code == 200, first.text
    original = first.json()

    duplicate = client.post("/api/courses", json={"topic": "Java OOP"})
    assert duplicate.status_code == 200, duplicate.text
    current = duplicate.json()
    assert current["course_id"] == original["course_id"] == "JAVA-OOP"
    assert current["display_name"] == original["display_name"]
    assert current["goal"]["target"] == "掌握 OOP"
    assert current["category_id"] == category["category_id"]
    assert current["duration_days"] == 30
    assert current["daily_minutes"] == 90


def test_chat_flow(client):
    r = client.post("/api/chat", json={"message": "你好"})
    assert r.status_code == 200, r.text
    assert r.json()["content"]
    assert r.json()["course_id"] is None

    # 课程对话
    course = client.post("/api/courses", json={"topic": "Java OOP"}).json()
    r = client.post("/api/chat", json={"message": "多态是什么？", "course_id": course["course_id"]})
    assert r.status_code == 200
    assert r.json()["course_id"] == course["course_id"]

    # 历史
    history = client.get("/api/chat", params={"course_id": course["course_id"]}).json()
    assert len(history["messages"]) == 2


def test_plan_step_id_requires_course_id(client):
    # 显式 plan_step_id 但缺少 course_id → 必须 404，
    # 绝不能静默降级为 General Chat（service contract：plan_step_id 必须有有效 course_id 做归属校验）
    r = client.post("/api/chat", json={"message": "你好", "plan_step_id": "S1"})
    assert r.status_code == 404, r.text


def test_profile_intent_via_chat(client):
    client.post("/api/chat", json={"message": "我会 Python 基础"})
    r = client.post("/api/chat", json={"message": "忘记我做过 FastAPI"})
    # 第一个意图写入 fact，第二个删除（不存在则 no-op）——API 不报错
    assert r.status_code == 200


# ---------------------------------------------------------------- P1-5.1 GET history ownership 404
def test_get_history_other_user_course_returns_404(client):
    # USER-A 创建课程
    ca = client.post(
        "/api/courses", json={"topic": "Python 数据分析"}, headers={"X-User-Id": "USER-A"}
    ).json()
    cid = ca["course_id"]
    # USER-B 访问 USER-A 课程 history → 404（不能 200/[] 把无权限与空历史混为一谈）
    r = client.get(
        "/api/chat", params={"course_id": cid}, headers={"X-User-Id": "USER-B"}
    )
    assert r.status_code == 404, r.text
    # USER-A 自己的 fresh 课程（合法 owner，无 conversation）→ 200 / []（empty state）
    r = client.get(
        "/api/chat", params={"course_id": cid}, headers={"X-User-Id": "USER-A"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["messages"] == []


# ---------------------------------------------------------------- P1-5.3 invalid plan_step → 404, no side effects
def test_invalid_plan_step_id_no_side_effects(client):
    import os

    from edu_agent.learner_model.service import LearnerModelService

    course = client.post("/api/courses", json={"topic": "Java OOP"}).json()
    cid = course["course_id"]
    # 非法 step + 「我会 Rust」→ 必须 404
    r = client.post(
        "/api/chat",
        json={"message": "我会 Rust", "course_id": cid, "plan_step_id": "PLANSTEP-NOPE"},
    )
    assert r.status_code == 404, r.text

    # 校验没有留下脏数据（验证发生在建会话 / 写画像 / 写事件之前）
    db = os.environ["LEARNER_MODEL_DB_PATH"]
    learner = LearnerModelService(db_path=db)
    # 没有 Rust profile fact
    rust = [
        f for f in learner.repo.list_profile_facts(USER)
        if "rust" in str(f.get("fact_value_json", "")).lower()
    ]
    assert rust == [], "invalid plan_step 不应写入 Rust profile fact"
    # 没有新 conversation
    convs = learner.repo._fetchall(
        "SELECT * FROM chat_conversations WHERE user_id=?", (USER,)
    )
    assert convs == [], "invalid plan_step 不应创建 conversation"
    # 没有 step event
    events = learner.repo.list_events(USER)
    step_events = [
        e for e in events
        if e["event_type"] in ("PLAN_STEP_COMPLETED", "PLAN_STEP_STARTED")
    ]
    assert step_events == [], "invalid plan_step 不应写入 step event"


# ---------------------------------------------------------------- P2-3 plan time bounds → 422
def test_generate_plan_invalid_time_bounds_422(client):
    course = client.post("/api/courses", json={"topic": "SQL", "goal": "掌握 SQL 查询"}).json()
    cid = course["course_id"]
    # duration_days 超出 [1,365] → 422（不跑完整 LLM workflow 后 DB 500）
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 999, "daily_minutes": 60},
    )
    assert r.status_code == 422, r.text
    # daily_minutes 超出 [5,600] → 422
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 14, "daily_minutes": 1},
    )
    assert r.status_code == 422, r.text
    # 合法值仍工作（offline fallback 路径）
    r = client.post(
        f"/api/courses/{cid}/plan/generate",
        json={"duration_days": 14, "daily_minutes": 60},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- Conversations（GPT 式最近对话）
def test_conversations_empty(client):
    assert client.get("/api/chat/conversations").json() == []


def test_conversation_title_listed(client):
    msg = "我想学习 Python 的数据分析基础"
    r = client.post("/api/chat", json={"message": msg})
    assert r.status_code == 200, r.text
    convs = client.get("/api/chat/conversations").json()
    assert len(convs) == 1
    # 首条用户消息后生成标题（<=36 字不截断）；course_id 为空=General
    assert convs[0]["title"] == msg
    assert convs[0]["course_id"] is None


def test_conversations_limit(client):
    # 生产语义：POST /api/chat 无 conversation_id 时复用 (user, course) 现有会话（GPT 式「继续当前对话」）。
    # 要产生多条对话，须显式走「新对话」POST /api/chat/conversations，再带 conversation_id 发消息。
    conv_ids = []
    for i in range(8):
        conv = client.post("/api/chat/conversations", json={}).json()
        conv_ids.append(conv["conversation_id"])
        client.post(
            "/api/chat",
            json={"message": f"普通对话第 {i} 条", "conversation_id": conv["conversation_id"]},
        )
    assert len(conv_ids) == 8
    assert len(client.get("/api/chat/conversations", params={"limit": 6}).json()) == 6
    assert len(client.get("/api/chat/conversations", params={"limit": 20}).json()) == 8


def test_conversation_course_filter(client):
    course = client.post("/api/courses", json={"topic": "Java OOP"}).json()
    cid = course["course_id"]
    client.post("/api/chat", json={"message": "普通问题"})  # General
    r = client.post("/api/chat", json={"message": "多态是什么", "course_id": cid})
    assert r.status_code == 200

    general = client.get("/api/chat/conversations").json()
    course_conv = client.get("/api/chat/conversations", params={"course_id": cid}).json()
    assert len(general) == 1 and general[0]["course_id"] is None
    assert len(course_conv) == 1 and course_conv[0]["course_id"] == cid


def test_conversations_other_user_course_404(client):
    course = client.post(
        "/api/courses", json={"topic": "Python"}, headers={"X-User-Id": "USER-A"}
    ).json()
    cid = course["course_id"]
    # USER-B 列 USER-A 的课程对话 → 404（ownership，信息隐藏）
    r = client.get(
        "/api/chat/conversations", params={"course_id": cid}, headers={"X-User-Id": "USER-B"}
    )
    assert r.status_code == 404, r.text


# ================================================================ Final Freeze: Category 边界
def test_category_delete_keeps_course(client):
    """删除分类 → 课程保留 + category_id=null；Goal 等 Adaptive 数据不受影响。"""
    cat = client.post("/api/course-categories", json={"name": "Python"},
                      headers={"X-User-Id": "USER-A"}).json()
    cid = cat["category_id"]
    course = client.post("/api/courses", json={"topic": "Python 数据分析", "category_id": cid},
                         headers={"X-User-Id": "USER-A"}).json()
    assert course["category_id"] == cid
    assert client.delete(f"/api/course-categories/{cid}",
                         headers={"X-User-Id": "USER-A"}).status_code == 204
    after = client.get(f"/api/courses/{course['course_id']}",
                       headers={"X-User-Id": "USER-A"}).json()
    assert after["category_id"] is None
    assert after["goal"] is not None  # Goal / Adaptive 数据不变


def test_category_ownership_user_scoped(client):
    """USER-B 不能把课程归入 USER-A 的分类（ownership-first，404）；A 自己可以。"""
    cat = client.post("/api/course-categories", json={"name": "私有"},
                      headers={"X-User-Id": "USER-A"}).json()
    cid = cat["category_id"]
    course_b = client.post("/api/courses", json={"topic": "B 的课"},
                           headers={"X-User-Id": "USER-B"}).json()
    r = client.patch(f"/api/courses/{course_b['course_id']}", json={"category_id": cid},
                     headers={"X-User-Id": "USER-B"})
    assert r.status_code == 404, r.text
    course_a = client.post("/api/courses", json={"topic": "A 的课"},
                           headers={"X-User-Id": "USER-A"}).json()
    r2 = client.patch(f"/api/courses/{course_a['course_id']}", json={"category_id": cid},
                      headers={"X-User-Id": "USER-A"})
    assert r2.status_code == 200 and r2.json()["category_id"] == cid


def test_category_fk_rejects_dead_category_id(client):
    """分类已删后再引用 → 404 且课程 category_id 保持 null（不留 orphan）。"""
    cat = client.post("/api/course-categories", json={"name": "临时"},
                      headers={"X-User-Id": "USER-A"}).json()
    cid = cat["category_id"]
    course = client.post("/api/courses", json={"topic": "FK 课"},
                         headers={"X-User-Id": "USER-A"}).json()
    client.delete(f"/api/course-categories/{cid}", headers={"X-User-Id": "USER-A"})
    r = client.patch(f"/api/courses/{course['course_id']}", json={"category_id": cid},
                     headers={"X-User-Id": "USER-A"})
    assert r.status_code == 404, r.text
    after = client.get(f"/api/courses/{course['course_id']}",
                       headers={"X-User-Id": "USER-A"}).json()
    assert after["category_id"] is None


def test_conversations_limit_bounds(client):
    """API limit bounds：1 <= limit <= 20（越界 422）。"""
    assert client.get("/api/chat/conversations", params={"limit": 0}).status_code == 422
    assert client.get("/api/chat/conversations", params={"limit": 21}).status_code == 422
    assert client.get("/api/chat/conversations", params={"limit": 20}).status_code == 200
