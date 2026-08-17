"""画像抽取与记忆意图的单元 / 行为测试。

覆盖：
- _normalize_ai_intents 安全边界（LLM 无删除权 / 偏好白名单 / fact_key 规则 /
  长度上限 / 敏感信息红线 / 条数上限 / scope 前缀）
- _worth_extracting 成本闸门（无自述信号不调抽取 LLM）
- 主路径 vs fallback：LLM 成功返回 [] 时正则误报不入库；LLM 失败（None）才退回正则
- 删除确定性优先且不阻断同消息其余抽取（「忘记 X，对了我是…」两句都生效）
- 抽取上下文携带已有画像（含跨课程背景隔离）
- ChatContext 课程背景 fact 排在全局 fact 之前
- 抽取超时不阻塞回复，后台仍完成落库
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402

from edu_agent.application import chat_service  # noqa: E402
from edu_agent.application.chat_service import (  # noqa: E402
    ChatService,
    _existing_profile_text,
    _normalize_ai_intents,
    _worth_extracting,
)
from edu_agent.learner_model.service import LearnerModelService  # noqa: E402

USER = "STU-EXTRACT"


@pytest.fixture()
def learner(tmp_path):
    return LearnerModelService(db_path=str(tmp_path / "lm.db"))


# ----------------------------------------------------------------------
# _normalize_ai_intents：LLM 输出的安全边界
# ----------------------------------------------------------------------
def test_normalize_rejects_llm_delete_and_bad_actions():
    """LLM 永远没有删除权；未知 action 一律丢弃。"""
    payload = [
        {"action": "delete_fact", "forget_raw": "python"},
        {"action": "wipe_profile"},
        "not-a-dict",
    ]
    assert _normalize_ai_intents(payload) == []


def test_normalize_preference_whitelist():
    out = _normalize_ai_intents([
        {"action": "set_preference", "preference_key": "evil_key", "direction": "pos"},
        {"action": "set_preference", "preference_key": "concise_first", "direction": "pos"},
        {"action": "set_preference", "preference_key": "worked_example", "direction": "sideways"},
    ])
    assert [i["preference_key"] for i in out] == ["concise_first"]


def test_normalize_fact_key_and_value_rules():
    bad_keys = [
        {"action": "set_fact", "fact_key": "Bad Key", "fact_value": "x"},
        {"action": "set_fact", "fact_key": "", "fact_value": "x"},
        {"action": "set_fact", "fact_key": "1abc", "fact_value": "x"},
        {"action": "set_fact", "fact_key": "x" * 80, "fact_value": "x"},
    ]
    assert _normalize_ai_intents(bad_keys) == []
    assert _normalize_ai_intents(
        [{"action": "set_fact", "fact_key": "skill_python", "fact_value": "x" * 161}]
    ) == []
    ok = _normalize_ai_intents(
        [{"action": "set_fact", "fact_key": "skill_python", "fact_value": "Python 基础"}]
    )
    assert ok and ok[0]["fact_key"] == "skill_python"


def test_normalize_rejects_sensitive_values():
    """手机号 / 邮箱 / API key / 密码等敏感内容直接丢弃。"""
    payload = [
        {"action": "set_fact", "fact_key": "contact", "fact_value": "我的手机号 13812345678"},
        {"action": "set_fact", "fact_key": "email_x", "fact_value": "a@b.com"},
        {"action": "add_memory", "content": "token 是 sk-abcdef0123456789abcd", "category": "experience"},
        {"action": "add_memory", "content": "我的密码是 123", "category": "experience"},
    ]
    assert _normalize_ai_intents(payload) == []


def test_normalize_memory_category_and_length():
    out = _normalize_ai_intents([
        {"action": "add_memory", "content": "用户做过数据分析", "category": "bogus"},
        {"action": "add_memory", "content": "x" * 241, "category": "experience"},
        {"action": "add_memory", "content": "用户做过数据分析", "category": "experience"},
    ])
    assert len(out) == 1
    assert out[0]["category"] == "experience"


def test_normalize_course_scope_and_item_cap():
    payload = [
        {"action": "set_fact", "fact_key": "level", "fact_value": "入门", "scope": "course"}
        for _ in range(15)
    ]
    out = _normalize_ai_intents(payload, course_id="CUSTOM-PY-1234ABCD")
    assert len(out) == 12, "单轮最多 12 条意图"
    assert all(i["fact_key"].startswith("background:CUSTOM-PY-1234ABCD:") for i in out)
    # 无 course_id 时 scope=course 降级为 global（key 不加前缀）
    global_out = _normalize_ai_intents(
        [{"action": "set_fact", "fact_key": "level", "fact_value": "入门", "scope": "course"}]
    )
    assert global_out[0]["fact_key"] == "level"


# ----------------------------------------------------------------------
# _worth_extracting：成本闸门
# ----------------------------------------------------------------------
def test_worth_extracting_gate():
    assert _worth_extracting("我会 Python") is True
    assert _worth_extracting("之前做过数据分析") is True
    assert _worth_extracting("I'm a CS student") is True
    assert _worth_extracting("什么是递归") is False
    assert _worth_extracting("Docker 怎么看日志") is False
    assert _worth_extracting("你好") is False


def test_gate_skips_llm_call(learner, monkeypatch):
    """无自述信号的消息不应调抽取 LLM。"""
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", spy)
    svc = ChatService(learner=learner)
    svc.chat(USER, "什么是递归")
    assert calls == []


# ----------------------------------------------------------------------
# 主路径 vs fallback
# ----------------------------------------------------------------------
def test_llm_success_empty_suppresses_regex_false_positive(learner, monkeypatch):
    """LLM 判定「无值得保存」后，正则误报（我会尽快…→ skill:尽快）不得入库。"""
    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", lambda *a, **k: [])
    svc = ChatService(learner=learner)
    svc.chat(USER, "我会尽快学完这门课")
    assert learner.repo.list_profile_facts(USER) == []


def test_llm_failure_falls_back_to_regex(learner, monkeypatch):
    """LLM 不可用（None）时退回确定性正则（离线环境的既有行为）。"""
    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", lambda *a, **k: None)
    svc = ChatService(learner=learner)
    svc.chat(USER, "我会 FastAPI 和 Docker")
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER)}
    assert {"skill:fastapi", "skill:docker"} <= keys


def test_delete_and_extraction_coexist(learner, monkeypatch):
    """「忘记 X，对了我是…」：删除确定性生效，且不阻断同消息其余信息的抽取。"""
    learner.set_profile_fact(USER, "skill:rust", "Rust")

    def fake_extract(user_id, message, history, course_id, lm):
        return [{"action": "set_fact", "fact_key": "education_field",
                 "fact_value": "数学专业", "category": "background"}]

    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", fake_extract)
    svc = ChatService(learner=learner)
    reply = svc.chat(USER, "忘记我学过 Rust，对了我是数学专业的")
    keys = {f["fact_key"] for f in learner.repo.list_profile_facts(USER)}
    assert "skill:rust" not in keys, "确定性删除必须生效"
    assert "education_field" in keys, "删除不应阻断同消息其余信息的抽取"
    assert any(u.startswith("deleted:skill:rust") for u in reply["profile_updates"])


def test_extract_prompt_contains_existing_profile(learner, monkeypatch):
    """抽取调用能看到已有画像（供 LLM 去重），且不含其他课程的背景。"""
    from edu_agent.application import course_service

    captured = {}

    def fake_extract(user_id, message, history, course_id, lm):
        captured["profile"] = _existing_profile_text(user_id, course_id, lm)
        return []

    course = course_service.create_course(USER, "Python 数据分析", learner=learner)
    cid = course["course_id"]
    learner.set_profile_fact(USER, "skill:python", "Python")
    learner.set_profile_fact(USER, f"background:{cid}", "数据分析")
    learner.set_profile_fact(USER, "background:CUSTOM-JAVA-ZZZZZZZZ", "Java 后端")
    learner.add_memory(USER, "用户曾做过：电商后台项目", category="experience")
    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", fake_extract)

    svc = ChatService(learner=learner)
    svc.chat(USER, "我会 Go 语言", course_id=cid)
    assert "已掌握 python" in captured["profile"]
    assert "课程背景：数据分析" in captured["profile"]
    assert "Java 后端" not in captured["profile"], "其他课程背景不得进入抽取上下文"
    assert "电商后台项目" in captured["profile"]


# ----------------------------------------------------------------------
# ChatContext：课程背景 fact 优先
# ----------------------------------------------------------------------
def test_chat_context_course_background_first(learner):
    """课程背景 fact 排在全局 fact 之前（即使全局 fact 更新时间更晚）。"""
    from edu_agent.application import course_service

    course = course_service.create_course(USER, "Python 数据分析", learner=learner)
    cid = course["course_id"]
    learner.set_profile_fact(USER, f"background:{cid}", "数据分析")
    learner.set_profile_fact(USER, "skill:python", "Python")  # 更晚写入 → updated_at 在前

    svc = ChatService(learner=learner)
    prompt = svc._build_context(USER, cid, "什么是 DataFrame")
    assert prompt.index("课程背景：数据分析") < prompt.index("已掌握 python")


# ----------------------------------------------------------------------
# 抽取超时不阻塞回复
# ----------------------------------------------------------------------
def test_slow_extraction_does_not_block_reply(learner, monkeypatch):
    """抽取超限：回复立即返回（不含该增量），后台线程仍完成落库。"""

    def slow_extract(*a, **k):
        time.sleep(0.3)
        return [{"action": "set_fact", "fact_key": "education_field",
                 "fact_value": "物理专业", "category": "background"}]

    monkeypatch.setattr(chat_service, "_extract_ai_memory_intents", slow_extract)
    monkeypatch.setattr(chat_service, "_MEMORY_WAIT_SECONDS", 0)
    svc = ChatService(learner=learner)
    reply = svc.chat(USER, "我是物理专业的")
    assert reply["content"], "回复必须正常返回"
    assert not any("education_field" in u for u in reply["profile_updates"])

    deadline = time.time() + 5
    while time.time() < deadline:
        if any(f["fact_key"] == "education_field"
               for f in learner.repo.list_profile_facts(USER)):
            break
        time.sleep(0.05)
    assert any(f["fact_key"] == "education_field"
               for f in learner.repo.list_profile_facts(USER)), "后台抽取最终落库"
