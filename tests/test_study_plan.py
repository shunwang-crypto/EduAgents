import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.config.settings import get_settings  # noqa: E402
from edu_agent.workflows.study_plan.input_parser import (  # noqa: E402
    ParsedStudentInput,
    input_parser_agent,
    parse_student_input,
)
from edu_agent.workflows.study_plan.schemas import StudentInput  # noqa: E402
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow  # noqa: E402


def test_settings_defaults_are_loadable():
    settings = get_settings()

    assert settings.openai_model


def test_parse_student_input_from_quick_description():
    parsed = parse_student_input(
        "我想学习 Python 数据分析，基础是会基础 Python，14 天，每天 1.5 小时，目标是完成一个数据分析报告"
    )

    assert parsed.topic == "Python 数据分析"
    assert parsed.level == "会基础 Python"
    assert parsed.days == 14
    assert parsed.daily_time == "1.5 小时"
    assert parsed.goal == "完成一个数据分析报告"
    assert parsed.missing_fields == []


def test_parse_student_input_reports_missing_fields():
    parsed = parse_student_input("我想学习二叉树，7 天")

    assert parsed.topic == "二叉树"
    assert parsed.days == 7
    assert "当前基础" in parsed.missing_fields
    assert "每天学习时间" in parsed.missing_fields
    assert "学习目标" in parsed.missing_fields


def test_parse_student_input_handles_long_quick_description():
    parsed = parse_student_input(
        "我想在 21 天内系统学习 LangChain Agent 和 LlamaIndex RAG，"
        "我会 Python 基础和简单 API 调用，但不熟悉异步、Pydantic、向量数据库和工具调用；"
        "每天最多 45 分钟，目标是能做出一个教育智能体应用，支持课程资料问答、学习计划生成、联网搜索和最终 Markdown 汇报。"
    )

    assert parsed.topic == "LangChain Agent 和 LlamaIndex RAG"
    assert parsed.days == 21
    assert parsed.daily_time == "45 分钟"
    assert "Python 基础和简单 API 调用" in parsed.level
    assert "Pydantic" in parsed.level
    assert "教育智能体应用" in parsed.goal
    assert parsed.missing_fields == []


def test_input_parser_agent_uses_structured_llm(monkeypatch):
    from edu_agent.workflows.study_plan import input_parser as parser_module

    def fake_get_llm(temperature):
        assert temperature == 0.0
        return object()

    def fake_invoke_structured_output(prompt_text, schema, values, llm):
        assert schema is ParsedStudentInput
        assert "用户原始输入" in prompt_text
        assert values["user_text"] == "帮我学 AI Agent"
        return ParsedStudentInput(
            topic="AI Agent",
            level="会 Python 基础",
            days=10,
            daily_time="1 小时",
            goal="完成一个智能体应用",
        )

    monkeypatch.setattr(parser_module, "get_llm", fake_get_llm)
    monkeypatch.setattr(
        parser_module,
        "invoke_structured_output",
        fake_invoke_structured_output,
    )

    parsed = input_parser_agent("帮我学 AI Agent")

    assert parsed.topic == "AI Agent"
    assert parsed.level == "会 Python 基础"
    assert parsed.missing_fields == []


def test_analyzer_passes_empty_plan_context_to_required_prompt(monkeypatch):
    from edu_agent.workflows.study_plan import agents
    from edu_agent.workflows.study_plan.schemas import AnalysisResult

    captured = {}

    monkeypatch.setattr(agents, "get_llm", lambda temperature: object())

    def fake_invoke(prompt_text, schema, values, llm):
        captured.update(values)
        return AnalysisResult(
            topic="PyTorch",
            level_summary="基础",
            goal_summary="目标",
            prerequisites=[],
            need_web_search=False,
            search_queries=[],
        )

    monkeypatch.setattr(agents, "invoke_structured_output", fake_invoke)
    agents.analyzer_agent(
        StudentInput(topic="PyTorch", days=7, daily_time="60分钟", goal="掌握 Tensor")
    )
    assert captured["plan_context"] == ""


def test_workflow_returns_displayable_fallback_without_api_key(monkeypatch):
    # 清掉所有模型配置（含 .env 里的 OpenCode Zen base_url），确保走降级模板而非真实网络
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENCODE_ZEN_API_KEY",
        "OPENCODE_ZEN_BASE_URL",
        "XINGCHEN_API_KEY",
        "XINGCHEN_BASE_URL",
    ):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()

    student_input = StudentInput(
        topic="Python 数据分析",
        level="会基础 Python",
        days=2,
        daily_time="1 小时",
        goal="能完成一个简单数据分析报告",
    )

    result = run_study_plan_workflow(student_input)

    assert result["analysis"].topic == "Python 数据分析"
    assert result["research"].search_enabled is False
    assert "# Python 数据分析 学习规划" in result["final_plan"]
