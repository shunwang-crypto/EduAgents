import json
import sys
from pathlib import Path

import streamlit as st
from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.config.settings import get_settings  # noqa: E402
from edu_agent.workflows.study_plan.input_parser import input_parser_agent  # noqa: E402
from edu_agent.workflows.study_plan.schemas import StudentInput  # noqa: E402
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow  # noqa: E402


def _to_json(value) -> str:
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(), ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _resources_to_markdown(research) -> str:
    if not research.resources:
        return research.summary

    lines = [research.summary, ""]
    for index, resource in enumerate(research.resources, start=1):
        title = resource.title or f"资源 {index}"
        if resource.url:
            lines.append(f"{index}. [{title}]({resource.url})")
        else:
            lines.append(f"{index}. {title}")
        if resource.summary:
            lines.append(f"   - {resource.summary}")
        score = getattr(resource, "quality_score", None)
        source_type = getattr(resource, "source_type", None)
        if score or source_type:
            lines.append(f"   - 类型：{source_type or 'unknown'}；评分：{score or '未评分'}")
        reason = getattr(resource, "reason", "")
        suitable_stage = getattr(resource, "suitable_stage", "")
        if reason:
            lines.append(f"   - 评估：{reason}")
        if suitable_stage:
            lines.append(f"   - 适合阶段：{suitable_stage}")
    return "\n".join(lines)


def _list_to_markdown(items) -> str:
    if not items:
        return "暂无"
    return "\n".join(f"- {item}" for item in items)


def _search_status_text() -> str:
    return "已启用" if bool(get_settings().tavily_api_key) else "未启用"


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 当前流程")
        st.caption(
            "Analyzer -> Decomposer -> Researcher -> ResourceEvaluator -> "
            "Planner -> PracticeDesigner -> PlanValidator -> Reviewer"
        )
        st.divider()
        st.metric("联网搜索", _search_status_text())
        st.metric("输出格式", "Markdown")
        st.caption("联网搜索开启后会检索外部资料，并由 ResourceEvaluator 做质量筛选。")


def _render_quick_input() -> None:
    st.markdown('<div class="section-title">快速描述学习需求</div>', unsafe_allow_html=True)
    quick_text = st.text_area(
        "一句话学习需求",
        value=st.session_state.get("quick_learning_need", ""),
        placeholder="例如：我想学习 Python 数据分析，基础是会基础 Python，14 天，每天 1.5 小时，目标是完成一个数据分析报告",
        height=90,
    )

    if st.button("智能解析并填入表单", use_container_width=False):
        st.session_state["quick_learning_need"] = quick_text
        with st.spinner("正在解析学习需求..."):
            parsed = input_parser_agent(quick_text)

        if parsed.topic:
            st.session_state["form_topic"] = parsed.topic
        if parsed.level:
            st.session_state["form_level"] = parsed.level
        if parsed.days is not None:
            st.session_state["form_days"] = parsed.days
        if parsed.daily_time:
            st.session_state["form_daily_time"] = parsed.daily_time
        if parsed.goal:
            st.session_state["form_goal"] = parsed.goal

        if parsed.missing_fields:
            st.warning(f"快速描述缺少：{', '.join(parsed.missing_fields)}。请在下方表单补充。")
        else:
            st.success("已解析并填入下方表单，仍可手动修改。")


def _render_form() -> bool:
    st.markdown('<div class="section-title">学习需求</div>', unsafe_allow_html=True)
    with st.form("study_plan_form"):
        topic = st.text_input(
            "学习内容",
            value=st.session_state.get("form_topic", ""),
            placeholder="例如：Python 数据分析、二叉树、机器学习入门",
        )
        level = st.text_area(
            "当前基础",
            value=st.session_state.get("form_level", ""),
            placeholder="例如：会基础 Python，不熟悉 pandas 和可视化",
            height=120,
        )

        days_col, time_col = st.columns([0.42, 0.58])
        with days_col:
            days = st.number_input(
                "学习周期",
                min_value=1,
                max_value=180,
                value=int(st.session_state.get("form_days", 14)),
                step=1,
            )
        with time_col:
            daily_time = st.text_input(
                "每天学习时间",
                value=st.session_state.get("form_daily_time", "1.5 小时"),
            )

        goal = st.text_area(
            "学习目标",
            value=st.session_state.get("form_goal", ""),
            placeholder="例如：能独立完成一个数据清洗、分析和可视化报告",
            height=120,
        )

        submitted = st.form_submit_button("生成学习规划", use_container_width=True)

    if submitted:
        st.session_state["form_topic"] = topic
        st.session_state["form_level"] = level
        st.session_state["form_days"] = int(days)
        st.session_state["form_daily_time"] = daily_time
        st.session_state["form_goal"] = goal

        if not topic.strip() or not level.strip() or not daily_time.strip() or not goal.strip():
            st.warning("请完整填写学习内容、当前基础、每天学习时间和学习目标。")
            return False

        student_input = StudentInput(
            topic=topic.strip(),
            level=level.strip(),
            days=int(days),
            daily_time=daily_time.strip(),
            goal=goal.strip(),
        )

        try:
            with st.spinner("正在生成学习规划..."):
                result = run_study_plan_workflow(student_input)
        except Exception as exc:  # noqa: BLE001 - UI should show a friendly error
            st.error(f"生成失败：{exc}")
            return False

        st.session_state["study_plan_result"] = result
        st.session_state["student_input"] = student_input
        st.rerun()

    return False


def _render_intro_panel() -> None:
    st.markdown('<div class="section-title">工作流状态</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("#### 学习规划流程")
        st.markdown(
            "Analyzer -> Decomposer -> Researcher -> ResourceEvaluator -> "
            "Planner -> PracticeDesigner -> PlanValidator -> Reviewer"
        )
        st.divider()

        col_a, col_b = st.columns(2)
        col_a.metric("输出格式", "Markdown")
        col_b.metric("联网搜索", _search_status_text())

        if _search_status_text() == "未启用":
            st.info("当前未启用联网搜索，本次计划主要基于模型和学生输入生成。")
        else:
            st.success("联网搜索已启用，生成计划时会参考外部资料。")

        st.caption("学习计划会先分析需求和拆解内容，再筛选资料、生成计划、设计练习，并通过规则校验后交给 Reviewer 优化。")


def _render_summary(result: dict, student_input: StudentInput | None) -> None:
    analysis = result["analysis"]
    research = result["research"]

    st.markdown('<div class="section-title">结果摘要</div>', unsafe_allow_html=True)
    with st.container(border=True):
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("学习主题", analysis.topic)
        col_b.metric("学习周期", f"{student_input.days} 天" if student_input else "已生成")
        col_c.metric("每天学习时间", student_input.daily_time if student_input else "已生成")
        col_d.metric("联网搜索", "已启用" if research.search_enabled else "未启用")

        if not research.search_enabled:
            st.info("当前未启用联网搜索，本次计划主要基于模型和学生输入生成。")


def _render_final_plan(result: dict) -> None:
    st.markdown('<div class="section-title">最终学习计划</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="small-muted">已整理为可执行、可检查的学习规划。</div>', unsafe_allow_html=True)
        st.download_button(
            "下载 Markdown",
            data=result["final_plan"],
            file_name="study-plan.md",
            mime="text/markdown",
            use_container_width=False,
        )
        st.divider()
        st.markdown('<div class="plan-body">', unsafe_allow_html=True)
        st.markdown(result["final_plan"])
        st.markdown("</div>", unsafe_allow_html=True)


def _render_process_details(result: dict) -> None:
    analysis = result["analysis"]
    research = result["research"]
    decomposition = result.get("decomposition")
    evaluated_research = result.get("evaluated_research")
    practice_plan = result.get("practice_plan")
    validation = result.get("validation")
    review = result["review"]

    st.markdown('<div class="section-title">过程详情</div>', unsafe_allow_html=True)
    with st.expander("查看工作流过程详情", expanded=False):
        (
            tab_analysis,
            tab_decomposition,
            tab_search,
            tab_evaluation,
            tab_draft,
            tab_practice,
            tab_validation,
            tab_review,
            tab_json,
        ) = st.tabs(
            [
                "需求分析",
                "学习内容拆解",
                "联网搜索",
                "资源筛选",
                "初版计划",
                "练习设计",
                "规则校验",
                "Reviewer 检查",
                "结构化数据",
            ]
        )

        with tab_analysis:
            st.markdown("#### 当前基础分析")
            st.write(analysis.level_summary)
            st.markdown("#### 学习目标整理")
            st.write(analysis.goal_summary)
            st.markdown("#### 前置知识")
            st.markdown("\n".join(f"- {item}" for item in analysis.prerequisites))
            if analysis.search_queries:
                st.markdown("#### 搜索关键词")
                st.markdown(_list_to_markdown(analysis.search_queries))

        with tab_decomposition:
            if decomposition is None:
                st.info("暂无学习内容拆解结果。")
            else:
                st.markdown("#### 前置知识")
                st.markdown(_list_to_markdown(decomposition.prerequisite_concepts))
                st.markdown("#### 核心知识点")
                st.markdown(_list_to_markdown(decomposition.core_concepts))
                st.markdown("#### 推荐学习顺序")
                st.markdown(_list_to_markdown(decomposition.learning_sequence))
                st.markdown("#### 可能难点")
                st.markdown(_list_to_markdown(decomposition.difficulty_points))
                st.markdown("#### 阶段建议")
                st.markdown(_list_to_markdown(decomposition.stage_suggestions))
                st.markdown("#### 实践方向")
                st.markdown(_list_to_markdown(decomposition.practice_directions))

        with tab_search:
            st.markdown(_resources_to_markdown(research))
            if research.key_points:
                st.markdown("#### 关键知识点")
                st.markdown(_list_to_markdown(research.key_points))

        with tab_evaluation:
            if evaluated_research is None:
                st.info("暂无资源质量评估结果。")
            else:
                st.markdown(_resources_to_markdown(evaluated_research))
                if evaluated_research.key_points:
                    st.markdown("#### 筛选后关键点")
                    st.markdown(_list_to_markdown(evaluated_research.key_points))

        with tab_draft:
            st.markdown(result["draft_plan"].plan_markdown)

        with tab_practice:
            if practice_plan is None:
                st.info("暂无练习设计结果。")
            else:
                st.markdown("#### 练习摘要")
                st.write(practice_plan.practice_summary)
                st.markdown("#### 每日练习任务")
                st.markdown(_list_to_markdown(practice_plan.daily_practice_tasks))
                st.markdown("#### 阶段检查任务")
                st.markdown(_list_to_markdown(practice_plan.stage_check_tasks))
                st.markdown("#### 最终项目")
                st.write(practice_plan.final_project)
                st.markdown("#### 反思问题")
                st.markdown(_list_to_markdown(practice_plan.reflection_questions))

        with tab_validation:
            if validation is None:
                st.info("暂无规则校验结果。")
            else:
                status = "通过" if validation.passed else "需优化"
                st.metric("校验结果", status)
                st.markdown("#### 发现的问题")
                st.markdown(_list_to_markdown(validation.issues))
                st.markdown("#### 修改建议")
                st.markdown(_list_to_markdown(validation.suggestions))
                st.markdown("#### 已检查规则")
                st.markdown(_list_to_markdown(validation.checked_rules))

        with tab_review:
            st.markdown("#### 检查总结")
            st.write(review.review_summary)
            if review.problems_found:
                st.markdown("#### 发现的问题")
                st.markdown(_list_to_markdown(review.problems_found))

        with tab_json:
            st.json(
                {
                    "analysis": json.loads(_to_json(analysis)),
                    "decomposition": json.loads(_to_json(decomposition)),
                    "research": json.loads(_to_json(research)),
                    "evaluated_research": json.loads(_to_json(evaluated_research)),
                    "draft_plan": json.loads(_to_json(result["draft_plan"])),
                    "practice_plan": json.loads(_to_json(practice_plan)),
                    "validation": json.loads(_to_json(validation)),
                    "review": json.loads(_to_json(review)),
                }
            )


st.set_page_config(page_title="教育智能体", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    h1 {
        letter-spacing: 0;
        margin-bottom: 0.15rem;
    }
    h2, h3 {
        letter-spacing: 0;
    }
    div[data-testid="stForm"] {
        border: 1px solid #d9e0ea;
        border-radius: 8px;
        padding: 1.2rem;
        background: #fbfcfe;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #d9e0ea;
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        background: #ffffff;
    }
    .section-title {
        margin: 1rem 0 0.75rem;
        font-size: 1.05rem;
        font-weight: 700;
        color: #202936;
    }
    div[data-testid="stMarkdownContainer"] {
        line-height: 1.78;
        color: #1f2937;
    }
    div[data-testid="stMarkdownContainer"] h1 {
        font-size: 1.65rem;
        margin-top: 0.4rem;
    }
    div[data-testid="stMarkdownContainer"] h2 {
        font-size: 1.28rem;
        margin-top: 1.35rem;
        padding-top: 0.25rem;
    }
    div[data-testid="stMarkdownContainer"] h3 {
        font-size: 1.08rem;
        margin-top: 1.05rem;
    }
    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li {
        font-size: 0.98rem;
    }
    div[data-testid="stMarkdownContainer"] table {
        width: 100%;
        border-collapse: collapse;
        margin: 0.75rem 0 1.1rem;
        font-size: 0.94rem;
    }
    div[data-testid="stMarkdownContainer"] th,
    div[data-testid="stMarkdownContainer"] td {
        border: 1px solid #d9e0ea;
        padding: 0.55rem 0.65rem;
        vertical-align: top;
    }
    div[data-testid="stMarkdownContainer"] th {
        background: #f6f8fb;
        font-weight: 700;
    }
    .stButton > button,
    .stDownloadButton > button {
        border-radius: 8px;
        font-weight: 650;
    }
    .stButton > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] button {
        background: #2563eb;
        color: #ffffff;
        border: 1px solid #2563eb;
    }
    .stButton > button[kind="primary"]:hover,
    div[data-testid="stFormSubmitButton"] button:hover {
        background: #1d4ed8;
        border-color: #1d4ed8;
        color: #ffffff;
    }
    .small-muted {
        color: #64748b;
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

_render_sidebar()

st.title("教育智能体")
st.caption("学生学习规划工作流")
_render_quick_input()

result = st.session_state.get("study_plan_result")
last_input = st.session_state.get("student_input")

if result is None:
    left_col, right_col = st.columns([0.48, 0.52], gap="large")
    with left_col:
        _render_form()
    with right_col:
        _render_intro_panel()
else:
    with st.expander("调整学习需求并重新生成", expanded=False):
        _render_form()

    _render_summary(result, last_input)
    _render_final_plan(result)
    _render_process_details(result)
