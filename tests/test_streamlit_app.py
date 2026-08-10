import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map  # noqa: E402
from edu_agent.workflows.study_plan.schemas import (  # noqa: E402
    AnalysisResult,
    DecompositionResult,
    DraftPlan,
    EvaluatedResearchResult,
    PlanValidationResult,
    ResearchResult,
    ReviewResult,
    StudentInput,
)


@pytest.fixture(autouse=True)
def _isolate_persisted_data(tmp_path, monkeypatch):
    """测试期间把持久化目录重定向到临时目录，避免真实 data/ 数据干扰 AppTest。

    不隔离的话，本地生成的 data/study_plan.json、data/kb_sessions.json 会被
    _load_persisted_state() 加载，导致 workbench/会话断言不符合预期。
    """
    from edu_agent.tools import app_state_store, kb_store

    monkeypatch.setattr(
        app_state_store,
        "_FILES",
        {key: tmp_path / path.name for key, path in app_state_store._FILES.items()},
    )
    monkeypatch.setattr(kb_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kb_store, "STORE_PATH", tmp_path / "knowledge_base.json")
    yield


def test_streamlit_result_page_loads_knowledge_learning_view():
    student_input = StudentInput(
        topic="二叉树",
        level="会 Python 基础",
        days=3,
        daily_time="1 小时",
        goal="实现常见遍历",
    )
    analysis = AnalysisResult(
        topic="二叉树",
        level_summary="具备基础编程能力",
        goal_summary="实现并验证常见遍历",
        prerequisites=["递归"],
        need_web_search=False,
        search_queries=[],
    )
    decomposition = DecompositionResult(
        core_concepts=["节点结构", "前中后序遍历"],
        prerequisite_concepts=["递归"],
        learning_sequence=["递归", "节点结构", "遍历"],
        difficulty_points=["递归调用栈"],
        stage_suggestions=["基础准备", "核心学习", "综合实践"],
        application_directions=["手写遍历并验证"],
    )
    knowledge_map = build_knowledge_map(student_input, decomposition)
    research = ResearchResult(
        search_enabled=False,
        summary="未启用联网搜索",
        key_points=[],
        resources=[],
    )
    evaluated = EvaluatedResearchResult(
        search_enabled=False,
        summary="未启用联网搜索",
        key_points=[],
        resources=[],
    )
    draft = DraftPlan(plan_markdown="# 二叉树 学习规划\n\n## 每日计划\n\n完成遍历练习。")
    validation = PlanValidationResult(
        passed=True,
        issues=[],
        suggestions=[],
        checked_rules=["结构完整"],
    )
    review = ReviewResult(
        review_summary="计划可执行",
        problems_found=[],
        final_plan_markdown=draft.plan_markdown,
    )

    app = AppTest.from_file(PROJECT_ROOT / "app" / "streamlit_app.py")
    app.session_state["student_input"] = student_input
    app.session_state["study_plan_result"] = {
        "analysis": analysis,
        "decomposition": decomposition,
        "knowledge_map": knowledge_map,
        "research": research,
        "evaluated_research": evaluated,
        "draft_plan": draft,
        "validation": validation,
        "review": review,
        "final_plan": review.final_plan_markdown,
    }
    app.session_state["app_screen"] = "workbench"
    app.session_state["workbench_view"] = "知识学习"
    app.run(timeout=30)

    assert not app.exception
    assert "知识学习" in [item.value for item in app.segmented_control]
    assert any("知识点详情" in item.value for item in app.markdown)
    assert any("AI 助教" in item.label for item in app.button)
    assert any("生成专题讲解" in item.label for item in app.button)
    assert not any("围绕此知识点提问" in item.label for item in app.button)
    assert any("共 4 个知识点" in item.value for item in app.caption)

    app.segmented_control(key="workbench_view").set_value("学习概览").run(timeout=30)
    assert any("学习路径" in item.value for item in app.markdown)
    app.button(key="path-stage-2").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["selected_knowledge_id"] == "knowledge-2"
    assert app.session_state["knowledge_category"] == "核心知识"
    assert app.session_state["workbench_view"] == "知识学习"

    next(item for item in app.button if item.label == "AI 助教").click().run(timeout=30)
    assert not app.exception
    assert any("知识点独立会话" in item.value for item in app.caption)
    assert "knowledge-2" in app.session_state["knowledge_chat_histories"]

    app.button(key="close-ai-assistant").click().run(timeout=30)
    assert app.session_state["active_aux_panel"] is None
    assert not app.exception


def test_streamlit_default_page_loads_workflow_center():
    app = AppTest.from_file(PROJECT_ROOT / "app" / "streamlit_app.py")
    app.run(timeout=30)

    assert not app.exception
    assert any("工作流中心" in item.value for item in app.markdown)
    assert any("启动学习规划" in item.label for item in app.button)


def test_streamlit_input_form_reads_parsed_session_values():
    app = AppTest.from_file(PROJECT_ROOT / "app" / "streamlit_app.py")
    app.session_state["app_screen"] = "study_plan_input"
    app.session_state["form_topic"] = "机械振动"
    app.session_state["form_level"] = "学过高等数学和理论力学"
    app.session_state["form_days"] = 10
    app.session_state["form_daily_time"] = "每天 60 分钟"
    app.session_state["form_goal"] = "能够建立单自由度振动模型"
    app.run(timeout=30)

    assert not app.exception
    assert app.text_input(key="form_topic").value == "机械振动"
    assert app.text_area(key="form_level").value == "学过高等数学和理论力学"
    assert app.number_input(key="form_days").value == 10
    assert app.text_input(key="form_daily_time").value == "每天 60 分钟"
    assert app.text_area(key="form_goal").value == "能够建立单自由度振动模型"


def test_streamlit_kb_qa_page_loads_gpt_style_chat():
    app = AppTest.from_file(PROJECT_ROOT / "app" / "streamlit_app.py")
    app.session_state["app_screen"] = "kb_qa_chat"
    # 预置一个会话：页面渲染中途才创建会话会触发 st.rerun()，AppTest 单次 run
    # 不会执行 rerun 后的第二次渲染，侧栏 radio 就看不到，故先预置。
    app.session_state["kb_sessions"] = {
        "会话 1": {"title": "新对话", "messages": []},
    }
    app.session_state["kb_active_session"] = "会话 1"
    app.run(timeout=30)

    assert not app.exception
    assert any("知识库问答" in tab.label for tab in app.tabs) or any(
        "知识库问答" in item.value for item in app.markdown
    )
    assert len(app.chat_input) >= 1
    assert any("新建对话" in item.label for item in app.button)
    assert "会话 1" in [item.value for item in app.radio] or any(
        "会话 1" in [opt for opt in item.options] for item in app.radio
    ) or any("会话 1" in str(item) for item in app.radio)
