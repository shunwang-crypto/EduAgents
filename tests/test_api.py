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

    # 获取/重命名
    cid = course["course_id"]
    assert client.get(f"/api/courses/{cid}").status_code == 200
    r = client.patch(f"/api/courses/{cid}", json={"title": "Python 数据分析进阶"})
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


def test_profile_intent_via_chat(client):
    client.post("/api/chat", json={"message": "我会 Python 基础"})
    r = client.post("/api/chat", json={"message": "忘记我做过 FastAPI"})
    # 第一个意图写入 fact，第二个删除（不存在则 no-op）——API 不报错
    assert r.status_code == 200
