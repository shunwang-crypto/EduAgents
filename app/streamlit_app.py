import html
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
from edu_agent.tools.course_kb import CourseKnowledgeBase  # noqa: E402
from edu_agent.workflows.kb_qa.schemas import KbAnswer  # noqa: E402
from edu_agent.tools import app_state_store, kb_store  # noqa: E402
from edu_agent.workflows.kb_qa.workflow import run_kb_qa_workflow  # noqa: E402
from edu_agent.workflows.plan_chat.schemas import ChatTurn  # noqa: E402
from edu_agent.workflows.plan_chat.workflow import answer_plan_question  # noqa: E402
from edu_agent.workflows.study_plan.input_parser import input_parser_agent  # noqa: E402
from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map  # noqa: E402
from edu_agent.workflows.study_plan.schemas import (  # noqa: E402
    KnowledgeMap,
    KnowledgeNode,
    StudentInput,
)
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow  # noqa: E402
from edu_agent.workflows.topic_tutor.schemas import TopicDetail  # noqa: E402
from edu_agent.workflows.topic_tutor.workflow import run_topic_tutor_workflow  # noqa: E402


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


# ---------------------------------------------------------------------------
# 持久化辅助：学习计划 / 学生输入 / 会话历史 / 学生画像 写入磁盘
# ---------------------------------------------------------------------------


def _persist_study_plan() -> None:
    """把当前学习计划结果 + 学生输入落到 data/study_plan.json。"""
    result = st.session_state.get("study_plan_result")
    student_input = st.session_state.get("student_input")
    if not result or not student_input:
        app_state_store.save("study_plan", None)
        return
    app_state_store.save(
        "study_plan",
        {"result": result, "student_input": student_input},
    )


def _persist_kb_sessions() -> None:
    """把当前会话历史落到 data/kb_sessions.json。"""
    sessions = st.session_state.get("kb_sessions")
    if not sessions:
        app_state_store.save("kb_sessions", None)
        return
    app_state_store.save("kb_sessions", dict(sessions))


def _load_persisted_state() -> None:
    """从磁盘恢复关键状态（启动时调用一次，仅在 session_state 缺失时填充）。"""
    from edu_agent.workflows.study_plan.schemas import DecompositionResult, StudentInput

    # 学习计划 + 学生输入
    if "study_plan_result" not in st.session_state:
        payload = app_state_store.load("study_plan")
        if isinstance(payload, dict):
            result = payload.get("result")
            student_input = payload.get("student_input")
            # 结构校验：旧版本数据（如 practice_directions 改名前的）反序列化会回落成
            # 普通 dict，workbench 无法访问 .prerequisite_concepts 等属性 → 不恢复。
            decomposition = result.get("decomposition") if isinstance(result, dict) else None
            if (
                isinstance(result, dict)
                and isinstance(decomposition, DecompositionResult)
                and isinstance(student_input, StudentInput)
            ):
                st.session_state["study_plan_result"] = result
                st.session_state["student_input"] = student_input
                st.session_state.setdefault("app_screen", "workbench")

    # 多会话历史
    if "kb_sessions" not in st.session_state:
        sessions = app_state_store.load("kb_sessions", default={})
        if isinstance(sessions, dict) and sessions:
            st.session_state["kb_sessions"] = sessions


def _render_quick_input() -> None:
    st.session_state.setdefault("quick_learning_need", "")
    st.markdown('<div class="section-title">快速描述学习需求</div>', unsafe_allow_html=True)
    quick_text = st.text_area(
        "一句话学习需求",
        placeholder="例如：我想学习 Python 数据分析，基础是会基础 Python，14 天，每天 1.5 小时，目标是完成一个数据分析报告",
        height=90,
        key="quick_learning_need",
    )

    if st.button("智能解析并填入表单", use_container_width=False):
        if not quick_text.strip():
            st.warning("请先输入学习需求。")
            return

        try:
            with st.spinner("正在解析学习需求..."):
                parsed = input_parser_agent(quick_text.strip())
        except Exception as exc:  # noqa: BLE001 - show parsing failures in the UI
            st.error(f"学习需求解析失败：{exc}")
            return

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
    st.session_state.setdefault("form_topic", "")
    st.session_state.setdefault("form_level", "")
    st.session_state.setdefault("form_days", 14)
    st.session_state.setdefault("form_daily_time", "1.5 小时")
    st.session_state.setdefault("form_goal", "")

    st.markdown('<div class="section-title">学习需求</div>', unsafe_allow_html=True)
    with st.form("study_plan_form"):
        topic = st.text_input(
            "学习内容",
            placeholder="例如：Python 数据分析、二叉树、机器学习入门",
            key="form_topic",
        )
        level = st.text_area(
            "当前基础",
            placeholder="例如：会基础 Python，不熟悉 pandas 和可视化",
            height=120,
            key="form_level",
        )

        days_col, time_col = st.columns([0.42, 0.58])
        with days_col:
            days = st.number_input(
                "学习周期",
                min_value=1,
                max_value=180,
                step=1,
                key="form_days",
            )
        with time_col:
            daily_time = st.text_input(
                "每天学习时间",
                key="form_daily_time",
            )

        goal = st.text_area(
            "学习目标",
            placeholder="例如：能独立完成一个数据清洗、分析和可视化报告",
            height=120,
            key="form_goal",
        )

        submitted = st.form_submit_button("生成学习规划", use_container_width=True)

    if submitted:
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
            # 自适应上下文：读 LearnerState → 决策 → 注入 Planner（画像不可用时为空）
            from edu_agent.adaptive.service import prepare_adaptive_context

            try:
                _ctx, _dec, plan_ctx = prepare_adaptive_context(
                    task_type="study_plan", query=topic.strip()
                )
                plan_learner_context = plan_ctx.get("learner_context", "")
                plan_adaptive_instructions = plan_ctx.get("adaptive_instructions", "")
            except Exception:  # noqa: BLE001
                plan_learner_context, plan_adaptive_instructions = "", ""

            with st.spinner("正在生成学习规划..."):
                result = run_study_plan_workflow(
                    student_input,
                    learner_context=plan_learner_context,
                    adaptive_instructions=plan_adaptive_instructions,
                )
        except Exception as exc:  # noqa: BLE001 - UI should show a friendly error
            st.error(f"生成失败：{exc}")
            return False

        st.session_state["study_plan_result"] = result
        st.session_state["student_input"] = student_input
        st.session_state["app_screen"] = "workbench"
        st.session_state["workbench_view"] = "学习概览"
        st.session_state["knowledge_statuses"] = {}
        _persist_study_plan()
        st.session_state["topic_details"] = {}
        st.session_state["knowledge_chat_histories"] = {}
        st.session_state.pop("selected_knowledge_id", None)
        st.rerun()

    return False


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


def _knowledge_statuses() -> dict[str, str]:
    return st.session_state.setdefault("knowledge_statuses", {})


def _activate_workbench_view(view_name: str) -> None:
    st.session_state["workbench_view"] = view_name
    st.session_state["active_aux_panel"] = None


def _set_app_screen(screen_name: str) -> None:
    st.session_state["app_screen"] = screen_name
    st.session_state["active_aux_panel"] = None


def _open_aux_panel(panel_name: str) -> None:
    st.session_state["active_aux_panel"] = panel_name


def _close_aux_panel() -> None:
    st.session_state["active_aux_panel"] = None


def _handle_workbench_view_change() -> None:
    st.session_state["active_aux_panel"] = None


def _select_knowledge_from_widget(widget_key: str) -> None:
    st.session_state["selected_knowledge_id"] = st.session_state[widget_key]


def _select_knowledge_node(node_id: str, category: str) -> None:
    st.session_state["selected_knowledge_id"] = node_id
    st.session_state["knowledge_category"] = category
    st.session_state[f"knowledge-nav-{category}"] = node_id
    st.session_state["workbench_view"] = "知识学习"
    st.session_state["active_aux_panel"] = None


def _select_first_node_in_category(first_node_ids: dict[str, str]) -> None:
    category = st.session_state.get("knowledge_category")
    if category in first_node_ids:
        st.session_state["selected_knowledge_id"] = first_node_ids[category]


def _update_knowledge_status(node_id: str, widget_key: str) -> None:
    _knowledge_statuses()[node_id] = st.session_state[widget_key]


def _selected_knowledge_node(knowledge_map: KnowledgeMap) -> KnowledgeNode:
    selected_id = st.session_state.get("selected_knowledge_id")
    by_id = {node.id: node for node in knowledge_map.nodes}
    if selected_id not in by_id:
        selected_id = (
            knowledge_map.recommended_path[0]
            if knowledge_map.recommended_path
            else knowledge_map.nodes[0].id
        )
        st.session_state["selected_knowledge_id"] = selected_id
    return by_id[selected_id]


def _render_learning_overview(
    result: dict,
    student_input: StudentInput | None,
    knowledge_map: KnowledgeMap,
) -> None:
    statuses = _knowledge_statuses()
    total = len(knowledge_map.nodes)
    completed = sum(
        1 for node in knowledge_map.nodes if statuses.get(node.id) == "已完成"
    )
    current = next(
        (node for node in knowledge_map.nodes if statuses.get(node.id) == "学习中"),
        _selected_knowledge_node(knowledge_map),
    )
    remaining_minutes = sum(
        node.estimated_minutes
        for node in knowledge_map.nodes
        if statuses.get(node.id) != "已完成"
    )
    progress = round((completed / total) * 100) if total else 0

    main_col, stats_col = st.columns([0.68, 0.32], gap="large")
    with main_col:
        st.markdown('<div class="section-title">当前学习任务</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.caption(
                f"{current.category} / {current.stage} / 建议 {current.estimated_minutes} 分钟"
            )
            st.markdown(f"### {current.title}")
            st.write(current.learning_objective)
            task_col, check_col = st.columns(2, gap="large")
            with task_col:
                st.markdown("**实践任务**")
                st.write(current.application_task)
            with check_col:
                st.markdown("**完成检查**")
                st.write(current.check_method)
            st.button(
                "进入知识学习",
                key="overview-open-knowledge",
                type="primary",
                on_click=_activate_workbench_view,
                args=("知识学习",),
            )

    with stats_col:
        st.markdown('<div class="section-title">计划进度</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.metric("完成率", f"{progress}%", border=False)
            st.progress(completed / total if total else 0)
            metric_a, metric_b = st.columns(2)
            metric_a.metric("知识点", f"{completed}/{total}", border=False)
            metric_b.metric(
                "预计剩余",
                f"{max(1, round(remaining_minutes / 60, 1))} 小时",
                border=False,
            )
            if student_input:
                st.caption(
                    f"学习周期 {student_input.days} 天 / 每天 {student_input.daily_time}"
                )

    _render_learning_path(knowledge_map)


def _render_learning_path(knowledge_map: KnowledgeMap) -> None:
    statuses = _knowledge_statuses()
    by_id = {node.id: node for node in knowledge_map.nodes}
    selected_id = _selected_knowledge_node(knowledge_map).id
    path = [
        by_id[node_id]
        for node_id in knowledge_map.recommended_path
        if node_id in by_id
    ]
    if not path:
        return

    stages: dict[str, list[KnowledgeNode]] = {}
    for node in path:
        stages.setdefault(node.stage, []).append(node)

    completed_stages = sum(
        all(statuses.get(node.id) == "已完成" for node in stage_nodes)
        for stage_nodes in stages.values()
    )
    st.markdown('<div class="section-title">学习路径</div>', unsafe_allow_html=True)
    progress_col, count_col = st.columns([0.82, 0.18], vertical_alignment="center")
    with progress_col:
        st.progress(completed_stages / len(stages))
    with count_col:
        st.caption(f"阶段完成 {completed_stages} / {len(stages)}")
    st.caption(f"按阶段查看整体路线；全部 {len(knowledge_map.nodes)} 个知识点在“知识学习”中分类展示。")

    status_styles: list[str] = []
    selected_stage = by_id[selected_id].stage
    for index, (stage, stage_nodes) in enumerate(stages.items(), start=1):
        if stage == selected_stage:
            continue
        stage_statuses = [statuses.get(node.id, "未开始") for node in stage_nodes]
        if all(status == "已完成" for status in stage_statuses):
            status_styles.append(
                f".st-key-path-stage-{index} button {{border-color:#86b89a;"
                "background:#f0fdf4;color:#166534;}}"
            )
        elif "需复习" in stage_statuses:
            status_styles.append(
                f".st-key-path-stage-{index} button {{border-color:#d6a852;"
                "background:#fffbeb;color:#92400e;}}"
            )
        elif "学习中" in stage_statuses:
            status_styles.append(
                f".st-key-path-stage-{index} button {{border-color:#7aa7e8;"
                "background:#eff6ff;color:#1d4ed8;}}"
            )
    if status_styles:
        st.markdown(f"<style>{''.join(status_styles)}</style>", unsafe_allow_html=True)

    with st.container(key="knowledge-path", horizontal=True, gap="small"):
        for index, (stage, stage_nodes) in enumerate(stages.items(), start=1):
            target = next(
                (
                    node
                    for node in stage_nodes
                    if statuses.get(node.id) != "已完成"
                ),
                stage_nodes[0],
            )
            st.button(
                f"阶段 {index}  {stage}",
                key=f"path-stage-{index}",
                type="primary" if stage == selected_stage else "secondary",
                on_click=_select_knowledge_node,
                args=(target.id, target.category),
                help=f"包含 {len(stage_nodes)} 个知识点，点击进入第一个未完成知识点",
            )


def _render_generated_topic_detail(detail: TopicDetail) -> None:
    st.markdown('<div class="section-title">专题学习材料</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"### {detail.title}")
        st.write(detail.learning_objective)
        explain_tab, example_tab, check_tab, resource_tab = st.tabs(
            ["核心讲解", "示例", "检查与下一步", "参考与追问"]
        )
        with explain_tab:
            st.markdown(detail.explanation_markdown)
        with example_tab:
            st.markdown(detail.example_markdown)
            st.markdown("#### 常见错误")
            st.markdown(_list_to_markdown(detail.common_mistakes))
        with check_tab:
            st.markdown("#### 完成检查")
            st.markdown(_list_to_markdown(detail.completion_checks))
            st.markdown("#### 下一步学习建议")
            st.markdown(_list_to_markdown(detail.next_learning_suggestions))
        with resource_tab:
            st.markdown("#### 参考资源")
            st.markdown(_list_to_markdown(detail.resource_urls))
            st.markdown("#### 可以继续问")
            st.markdown(_list_to_markdown(detail.suggested_questions))


def _render_knowledge_map(
    result: dict,
    student_input: StudentInput,
    knowledge_map: KnowledgeMap,
) -> None:
    categories: dict[str, list[KnowledgeNode]] = {}
    for node in knowledge_map.nodes:
        categories.setdefault(node.category, []).append(node)

    selected = _selected_knowledge_node(knowledge_map)
    if st.session_state.get("knowledge_category") not in categories:
        st.session_state["knowledge_category"] = selected.category

    category_summary = " / ".join(
        f"{category} {len(nodes)} 个" for category, nodes in categories.items()
    )
    st.caption(f"共 {len(knowledge_map.nodes)} 个知识点：{category_summary}")

    navigator, detail_panel = st.columns([0.28, 0.72], gap="large")
    with navigator:
        st.markdown("#### 知识目录")
        first_node_ids = {
            category: nodes[0].id for category, nodes in categories.items()
        }
        selected_category = st.selectbox(
            "知识分类",
            list(categories),
            format_func=lambda category: f"{category} ({len(categories[category])})",
            key="knowledge_category",
            on_change=_select_first_node_in_category,
            args=(first_node_ids,),
        )
        category_nodes = categories[selected_category]
        nav_key = f"knowledge-nav-{selected_category}"
        category_ids = [node.id for node in category_nodes]
        if st.session_state.get(nav_key) not in category_ids:
            st.session_state[nav_key] = (
                selected.id if selected.id in category_ids else category_ids[0]
            )

        status_labels = {
            "已完成": "已完成",
            "学习中": "学习中",
            "需复习": "需复习",
        }

        def format_nav_node(node_id: str) -> str:
            node = next(item for item in category_nodes if item.id == node_id)
            status = status_labels.get(_knowledge_statuses().get(node_id), "")
            return f"{node.title}  {status}".rstrip()

        selected_id = st.radio(
            "选择知识点",
            category_ids,
            format_func=format_nav_node,
            key=nav_key,
            label_visibility="collapsed",
            on_change=_select_knowledge_from_widget,
            args=(nav_key,),
        )
        st.session_state["selected_knowledge_id"] = selected_id
        selected = next(node for node in category_nodes if node.id == selected_id)
        st.caption("选择一个知识点，在右侧查看目标、任务和完成标准。")

    with detail_panel:
        st.markdown("#### 知识点详情")
        with st.container(border=True):
            st.markdown(f"### {selected.title}")
            st.caption(f"{selected.category} / {selected.stage}")
            st.write(selected.summary)

            meta_a, meta_b, meta_c = st.columns(3)
            meta_a.metric("难度", selected.difficulty)
            meta_b.metric("建议用时", f"{selected.estimated_minutes} 分钟")
            meta_c.metric("当前状态", _knowledge_statuses().get(selected.id, "未开始"))

            objective_col, task_col = st.columns(2, gap="large")
            with objective_col:
                st.markdown("**学习目标**")
                st.write(selected.learning_objective)
                st.markdown("**前置知识**")
                st.markdown(_list_to_markdown(selected.prerequisites))
            with task_col:
                st.markdown("**实践任务**")
                st.write(selected.application_task)
                st.markdown("**完成检查**")
                st.write(selected.check_method)

            status_options = ["未开始", "学习中", "已完成", "需复习"]
            status_key = f"status-{selected.id}"
            status = st.segmented_control(
                "学习状态",
                status_options,
                default=_knowledge_statuses().get(selected.id, "未开始"),
                key=status_key,
                on_change=_update_knowledge_status,
                args=(selected.id, status_key),
            ) or "未开始"
            _knowledge_statuses()[selected.id] = status

            tutor_clicked = st.button(
                "生成专题讲解",
                key=f"tutor-{selected.id}",
                type="primary",
                use_container_width=True,
            )

    if tutor_clicked:
        try:
            # 自适应上下文：按节点标题映射 KC → 决策 → 注入讲解 prompt
            from edu_agent.adaptive.service import decision_summary, prepare_adaptive_context
            from edu_agent.domain.learning.kc_graph import get_course

            course = get_course(_learner_state_bundle().course_id)
            kc_match = course.find_kc_by_title(selected.title) if course else None
            target_kc = kc_match.kc_id if kc_match else selected.title
            _emit_event("EXPLANATION_REQUESTED", kc_id=target_kc)
            try:
                _ctx, _dec, tutor_prompt_ctx = prepare_adaptive_context(
                    task_type="topic_tutor",
                    target_kc=target_kc,
                )
                learner_context = tutor_prompt_ctx.get("learner_context", "")
                adaptive_instructions = tutor_prompt_ctx.get("adaptive_instructions", "")
                decision_summary_text = "\n".join(
                    f"- {k}: {v}" for k, v in decision_summary(_dec).items() if k != "explain"
                )
            except Exception:  # noqa: BLE001
                learner_context, adaptive_instructions, decision_summary_text = "", "", ""

            with st.spinner(f"正在生成「{selected.title}」专题讲解..."):
                topic_detail = run_topic_tutor_workflow(
                    student_input=student_input,
                    knowledge_node=selected,
                    resources=result["evaluated_research"].resources,
                    learner_context=learner_context,
                    adaptive_instructions=adaptive_instructions,
                    adaptive_decision_summary=decision_summary_text,
                )
            st.session_state.setdefault("topic_details", {})[
                selected.id
            ] = topic_detail.model_dump()
        except Exception as exc:  # noqa: BLE001 - keep the learning view usable
            st.error(f"专题讲解生成失败：{exc}")


# ---------------------------------------------------------------------------
# 学习画像（Learner State 只读展示：数据来自 LearnerStateProvider，不在此修改画像）
# ---------------------------------------------------------------------------


def _learner_state_bundle():
    """读取 LearnerStateBundle（来自本地 SQLite Learner Model），失败返回空 bundle 不中断。"""
    from edu_agent.adaptive.service import load_bundle

    try:
        return load_bundle()
    except Exception:  # noqa: BLE001 - 画像服务不可用时前端仍可用
        from edu_agent.learner_model.schemas import LearnerStateBundle

        return LearnerStateBundle()


def _render_learner_state_panel(bundle=None) -> None:
    """本地动态学习画像：facts/goal/知识/能力/偏好/误解/记忆 + 变化记录 + 用户操作。"""
    from edu_agent.config.settings import get_settings
    from edu_agent.learner_model.service import LearnerModelService

    settings = get_settings()
    user_id = settings.learner_model_user_id
    course_id = settings.learner_model_course_id
    service = LearnerModelService()

    bundle = bundle or _learner_state_bundle()
    course_state = bundle.course_state
    global_state = bundle.global_state
    goal = bundle.active_goal
    profile = global_state.profile

    st.markdown(
        '<div class="section-title">动态学习画像（Local Learner Model · SQLite）</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"数据来源：本地 `data/learner_model.db` · 画像版本 v{course_state.state_version or '-'}"
        f" · 最近更新：{str(course_state.updated_at or '')[:19]}"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("用户", profile.display_name or profile.user_id or "未命名", border=False)
    col2.metric("当前课程", bundle.course_id, border=False)
    col3.metric("课程进度", f"{course_state.progress:.0%}", border=False)

    if goal:
        st.markdown(f"**当前目标**：{goal.goal_name}（进度 {goal.progress:.0%}）")
        if goal.target:
            st.caption(goal.target)

    # ---------------- 背景事实（可删除） ----------------
    facts = service.repo.list_profile_facts(user_id)
    st.markdown("#### 背景事实")
    if not facts:
        st.caption("暂无背景事实。可在「学习计划」提交时填写，或在下方手动添加。")
    for fact in facts:
        fkey = fact.get("fact_key", "")
        fvalue = fact.get("fact_value_json", "")
        fcol1, fcol2 = st.columns([0.75, 0.25])
        with fcol1:
            st.markdown(f"- **{fkey}**：`{fvalue}`（置信度 {fact.get('confidence', 0):.0%} · {fact.get('status')}）")
        with fcol2:
            if st.button("删除", key=f"del-fact-{fact.get('fact_id')}", help="用户明确删除该事实"):
                service.delete_profile_fact(user_id, fkey)
                st.toast(f"已删除事实：{fkey}")
                st.rerun()

    # ---------------- 掌握度 ----------------
    if course_state.knowledge:
        st.markdown("#### 知识掌握度")
        rows = []
        for item in sorted(course_state.knowledge, key=lambda k: k.mastery):
            status_icon = "✅" if item.mastery >= 0.7 else ("🔶" if item.mastery >= 0.3 else "❌")
            conf = item.confidence
            conf_text = f"{conf:.2f}" if conf is not None else "—"
            trend_text = item.trend or "—"
            rows.append(
                f"| {item.name or item.kc_id} | {item.mastery:.2f} | {conf_text} | "
                f"{status_icon} {item.status} | {trend_text} |"
            )
        st.markdown(
            "| 知识点 | 掌握度 | 置信度 | 状态 | 趋势 |\n"
            "| -- | -- | -- | -- | -- |\n" + "\n".join(rows)
        )
    else:
        st.caption("尚无知识点掌握数据（首次学习后由事件产生，不编造默认值）。")

    # ---------------- 能力 ----------------
    if course_state.abilities:
        st.markdown("#### 能力维度")
        ability_rows = [
            f"| {name} | {item.score:.2f} | "
            f"{item.confidence:.2f if item.confidence is not None else '—'} | "
            f"{item.trend or '—'} |"
            for name, item in sorted(course_state.abilities.items())
        ]
        st.markdown(
            "| 能力 | 分数 | 置信度 | 趋势 |\n| -- | -- | -- | -- |\n" + "\n".join(ability_rows)
        )

    # ---------------- 偏好（可纠正） ----------------
    st.markdown("#### 学习偏好")
    prefs = global_state.preferences
    pref_rows = service.repo.list_preferences(user_id, course_id)
    if pref_rows:
        for pref in pref_rows:
            pcol1, pcol2 = st.columns([0.7, 0.3])
            with pcol1:
                st.markdown(
                    f"- **{pref['preference_key']}**：score {pref['score']:.2f} · "
                    f"置信度 {pref['confidence']:.2f} · 样本 {pref['evidence_count']} · {pref['status']}"
                )
            with pcol2:
                direction = st.selectbox(
                    "纠正",
                    ["保持", "↑ 更喜欢", "↓ 不喜欢"],
                    key=f"pref-adj-{pref['preference_key']}",
                    label_visibility="collapsed",
                )
                if st.button("应用", key=f"pref-apply-{pref['preference_key']}"):
                    if direction == "↑ 更喜欢":
                        service.set_preference(user_id, pref["preference_key"], direction="pos")
                        st.toast(f"偏好已强化：{pref['preference_key']}")
                    elif direction == "↓ 不喜欢":
                        service.set_preference(user_id, pref["preference_key"], direction="neg")
                        st.toast(f"偏好已弱化：{pref['preference_key']}")
                    st.rerun()
    else:
        st.caption("暂无偏好记录（多次请求示例/图解等行为后自动积累）。")

    # ---------------- 误解（生命周期） ----------------
    if course_state.misconceptions:
        st.markdown("#### 已知误解")
        for m in course_state.misconceptions:
            status_label = {
                "candidate": "候选",
                "active": "活跃",
                "resolving": "解决中",
                "resolved": "已解决",
                "dormant": "休眠",
            }.get(m.status, m.status)
            st.markdown(
                f"- {m.kc_id}：{m.description}（{status_label} · 置信度 {m.confidence:.0%}"
                f" · 出现 {m.occurrence_count} 次）"
            )
    else:
        st.caption("暂无误解记录。")

    # ---------------- 语义记忆（可删除） ----------------
    memories = service.repo.list_memories(user_id, "")
    st.markdown("#### 长期记忆")
    if not memories:
        st.caption("暂无长期记忆。")
    for mem in memories:
        mcol1, mcol2 = st.columns([0.78, 0.22])
        with mcol1:
            st.markdown(f"- {mem.get('content', '')}（{mem.get('status')}）")
        with mcol2:
            if st.button("删除", key=f"del-mem-{mem.get('memory_id')}", help="用户明确删除该记忆"):
                service.delete_memory(user_id, mem.get("memory_id", ""))
                st.toast("已删除该记忆")
                st.rerun()

    # ---------------- 画像变化记录 ----------------
    st.markdown("#### 画像变化记录")
    changes = service.get_changes(user_id, course_id, limit=15)
    if not changes:
        st.caption("暂无画像变化（用户产生学习行为后自动记录）。")
    for ch in changes:
        st.markdown(
            f"- `{ch.get('operation')}` {ch.get('entity_type')}:{ch.get('entity_id')} "
            f"— {ch.get('reason', '')}（{str(ch.get('created_at', ''))[:19]}）"
        )

    st.caption("---")
    st.caption(
        "本页面展示本地 Dynamic Learner Model：事件 → 证据 → 定向更新 → 变化记录。"
        "画像支持新增/修改/强化/弱化/失效/解决/删除。"
    )


def _render_process_details(result: dict) -> None:
    analysis = result["analysis"]
    research = result["research"]
    decomposition = result.get("decomposition")
    evaluated_research = result.get("evaluated_research")
    validation = result.get("validation")
    review = result["review"]

    st.markdown('<div class="section-title">过程详情</div>', unsafe_allow_html=True)
    with st.expander("查看工作流过程详情", expanded=True):
        (
            tab_analysis,
            tab_decomposition,
            tab_search,
            tab_evaluation,
            tab_draft,
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
                st.markdown(_list_to_markdown(decomposition.application_directions))

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
                    "knowledge_map": json.loads(_to_json(result.get("knowledge_map"))),
                    "research": json.loads(_to_json(research)),
                    "evaluated_research": json.loads(_to_json(evaluated_research)),
                    "draft_plan": json.loads(_to_json(result["draft_plan"])),
                    "validation": json.loads(_to_json(validation)),
                    "review": json.loads(_to_json(review)),
                }
            )


def _kb_instance() -> CourseKnowledgeBase:
    """加载知识库：优先用 session 内的实例，否则从持久化存储重建（默认空库）。"""
    kb = st.session_state.get("kb_qa_base")
    if kb is None:
        kb = CourseKnowledgeBase.from_chunks(kb_store.load_chunks())
        st.session_state["kb_qa_base"] = kb
    return kb


# ---------------------------------------------------------------------------
# GPT 风格多会话管理
# ---------------------------------------------------------------------------


def _kb_sessions() -> dict:
    return st.session_state.setdefault("kb_sessions", {})


def _kb_create_session() -> str:
    sessions = _kb_sessions()
    counter = st.session_state.setdefault("kb_session_counter", 0) + 1
    st.session_state["kb_session_counter"] = counter
    session_id = f"会话 {counter}"
    sessions[session_id] = {"title": "新对话", "messages": []}
    st.session_state["kb_active_session"] = session_id
    _persist_kb_sessions()
    return session_id


def _kb_active_session_id() -> str:
    sessions = _kb_sessions()
    active = st.session_state.get("kb_active_session")
    if not active or active not in sessions:
        return _kb_create_session()
    return active


def _kb_migrate_legacy_history() -> None:
    """把旧版单会话历史（kb_qa_history）迁移为多会话结构，避免用户数据丢失。"""
    legacy = st.session_state.get("kb_qa_history")
    if legacy:
        session_id = _kb_create_session()
        _kb_sessions()[session_id] = {
            "title": legacy[0].get("content", "历史对话")[:14] if legacy else "历史对话",
            "messages": legacy,
        }
        st.session_state.pop("kb_qa_history", None)


def _kb_doc_summary(kb: CourseKnowledgeBase) -> str:
    docs: dict[str, int] = {}
    for chunk in kb.chunks:
        docs[chunk.doc_title] = docs.get(chunk.doc_title, 0) + 1
    return " / ".join(f"{name} {count} 块" for name, count in docs.items()) or "暂无内容"


def _last_user_question(history: list) -> str:
    for message in reversed(history):
        if message["role"] == "user":
            return message["content"]
    return ""


def _emit_event(
    event_type: str,
    kc_id: str = "",
    payload: dict | None = None,
    session_id: str = "",
) -> None:
    """把学习行为写成 Event 并更新本地 Learner Model（失败不阻塞主流程）。"""
    try:
        from edu_agent.config.settings import get_settings
        from edu_agent.learner_model.evidence.extractor import build_event
        from edu_agent.learner_model.service import LearnerModelService

        settings = get_settings()
        event = build_event(
            event_type=event_type,
            user_id=settings.learner_model_user_id,
            course_id=settings.learner_model_course_id,
            kc_id=kc_id,
            session_id=session_id or "",
            payload=payload or {},
        )
        service = LearnerModelService()
        if settings.learner_model_auto_update:
            service.apply_event(event)
        else:
            service.record_event(event)
    except Exception:  # noqa: BLE001 - 事件失败绝不阻塞用户请求
        pass


def _adaptive_qa_prompt_context(question: str) -> tuple[str, str, dict]:
    """构建 kb_qa 的自适应上下文 + 决策摘要（画像服务不可用时返回空，不中断）。"""
    from edu_agent.adaptive.service import decision_summary, prepare_adaptive_context

    try:
        _context, _decision, prompt_ctx = prepare_adaptive_context(
            task_type="adaptive_qa",
            query=question,
        )
        return (
            prompt_ctx.get("learner_context", ""),
            prompt_ctx.get("adaptive_instructions", ""),
            decision_summary(_decision),
        )
    except Exception:  # noqa: BLE001 - 画像服务不可用时走通用问答
        return "", "", {}


def _run_kb_answer(question: str, engine: str):
    """按引擎选择问答实现（当前统一走 kb_qa 手写流水线）。"""
    knowledge_base = _kb_instance()
    student_input = st.session_state.get("student_input")
    learner_context, adaptive_instructions, _ = _adaptive_qa_prompt_context(question)
    return run_kb_qa_workflow(
        question=question,
        knowledge_base=knowledge_base,
        student_input=student_input,
        learner_context=learner_context,
        adaptive_instructions=adaptive_instructions,
    )


def _send_kb_question(question: str, engine: str = "kb_qa") -> None:
    sessions = _kb_sessions()
    session_id = _kb_active_session_id()
    session = sessions[session_id]
    if session["title"] == "新对话":
        session["title"] = question[:14] + ("..." if len(question) > 14 else "")
    session["messages"].append({"role": "user", "content": question})
    _persist_kb_sessions()  # 用户消息即落盘，重启不丢对话内容
    # 学习行为事件：Emit Evidence（写 Outbox，不阻塞）
    _emit_event(
        "EDUCATIONAL_QUESTION_ASKED",
        payload={"question": question[:200]},
        session_id=session_id,
    )

    if engine == "kb_qa":
        # 双 rerun 模式：先写 user history + 标记 pending，让用户消息立即显示；
        # 下次 rerun（_render_kb_chat 中检测到 pending）才真正跑流式生成 AI。
        session["_pending_stream"] = engine
        st.rerun()
        return

    with st.spinner("正在结合知识库回答..."):
        answer = _run_kb_answer(question, engine)
    session["messages"].append(
        {
            "role": "assistant",
            "content": answer.answer_markdown,
            "meta": answer.model_dump(),
            "citations": [item.model_dump() for item in answer.citations],
        }
    )
    st.rerun()


def _collect_citation_messages() -> dict[int, list[dict]]:
    """从当前会话 messages 中直接收集所有带引用的 AI 消息，避免依赖上次 render 的 session_state。"""
    sessions = _kb_sessions()
    session_id = _kb_active_session_id()
    history = sessions.get(session_id, {}).get("messages", [])
    result: dict[int, list[dict]] = {}
    for i, m in enumerate(history):
        if m.get("role") == "assistant" and m.get("citations"):
            result[i] = m["citations"]
    return result


def _render_kb_chat(kb: CourseKnowledgeBase, engine: str = "kb_qa") -> None:
    sessions = _kb_sessions()
    session_id = _kb_active_session_id()
    session = sessions[session_id]
    history = session["messages"]

    # 收集所有带引用的 AI 消息（按消息索引→citations 字典）
    citation_messages = _collect_citation_messages()

    # 聊天消息区：用户右对齐胶囊，AI 无气泡左对齐
    st.markdown('<div class="kb-chat-messages">', unsafe_allow_html=True)
    for index, message in enumerate(history):
        role = message["role"]
        content = message["content"]
        if role == "user":
            content_html = html.escape(content).replace("\n", "<br>")
            st.markdown(
                f'<div class="chat-msg user-msg"><div class="user-bubble">{content_html}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="chat-msg ai-msg"><div class="ai-content">',
                unsafe_allow_html=True,
            )
            st.markdown(content, unsafe_allow_html=False)
            st.markdown("</div></div>", unsafe_allow_html=True)
            citations = message.get("citations", [])
            _render_kb_message_actions(session_id, index, message, citations)
    st.markdown("</div>", unsafe_allow_html=True)

    # 存为字典：{消息索引: citations}，右侧面板按需读取
    st.session_state["_kb_citation_messages"] = citation_messages

    # 流式生成回退：用户消息已显示，这里真正跑 AI 流式
    if session.get("_pending_stream") == engine:
        session["_pending_stream"] = None
        pending_question = _last_user_question(history)
        if pending_question:
            _run_stream_to_assistant(pending_question, engine, session_id, session)

    last_meta = history[-1].get("meta", {}) if history else {}
    if last_meta.get("intent") == "clarify":
        directions = last_meta.get("suggested_directions") or []
        if directions:
            st.markdown('<div class="clarify-prompt">选择你要细化的方向：</div>', unsafe_allow_html=True)
            last_question = _last_user_question(history[:-1])
            columns = st.columns(min(len(directions), 4))
            for column, direction in zip(columns, directions):
                if column.button(
                    direction,
                    key=f"kb-direction-{direction}-{session_id}",
                    use_container_width=True,
                ):
                    follow_up = (
                        f"请从「{direction}」的角度讲解：{last_question}"
                        if last_question
                        else f"我想从「{direction}」的角度学习"
                    )
                    _send_kb_question(follow_up, engine)
                    st.rerun()

    # 底部输入区：直接放输入框（不要再单加 disclaimer 文字，省垂直空间）
    with st.container(key="kb_input_footer"):
        question = st.chat_input("输入问题，例如：二叉树的前序遍历怎么写？")
    if question and question.strip():
        _send_kb_question(question.strip(), engine)
        st.rerun()


def _run_stream_to_assistant(question: str, engine: str, session_id: str, session: dict) -> None:
    """在二次 rerun 中执行真正的流式生成：用户消息已显示，这里用 GPT 风格 AI 容器流式写出真实文本。"""
    from edu_agent.workflows.kb_qa.workflow import stream_kb_qa_answer

    placeholder_index = len(session["messages"])
    session["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "meta": {"intent": "streaming", "ai_generated": True},
            "citations": [],
        }
    )
    captured: dict = {}

    def _capture(answer) -> None:
        captured["answer"] = answer

    # GPT 风格：无头像、无气泡，纯文本流式输出
    learner_context, adaptive_instructions, _decision_summary = _adaptive_qa_prompt_context(question)
    st.markdown('<div class="chat-msg ai-msg"><div class="ai-content">', unsafe_allow_html=True)
    full_text = st.write_stream(
        stream_kb_qa_answer(
            question=question,
            knowledge_base=_kb_instance(),
            student_input=st.session_state.get("student_input"),
            on_path=_capture,
            learner_context=learner_context,
            adaptive_instructions=adaptive_instructions,
        )
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

    meta_answer = captured.get("answer")
    if meta_answer is None:
        meta_answer = KbAnswer(
            intent="kb_answered",
            answer_markdown=full_text,
            citations=[],
            ai_generated=True,
        )
    session["messages"][placeholder_index] = {
        "role": "assistant",
        "content": full_text,
        "meta": meta_answer.model_dump(),
        "citations": [c.model_dump() for c in meta_answer.citations],
    }
    _persist_kb_sessions()  # AI 回复回填即落盘
    # 讲解已完成 → Emit Evidence（写 Outbox）
    _emit_event("EXPLANATION_DELIVERED", payload={"question": question[:200]}, session_id=session_id)
    st.rerun()


def _render_kb_message_actions(session_id: str, index: int, message: dict, citations: list | None = None) -> None:
    """AI 消息下方的 GPT 风格操作图标行：复制 / 赞 / 踩 / 重新生成 / 更多 + 引用编号按钮。"""
    MSG_KEY = message.get("content", "")

    def _do_copy() -> None:
        st.session_state["_kb_clipboard"] = MSG_KEY
        st.toast("已复制到剪贴板")

    def _do_up() -> None:
        st.session_state.setdefault("kb_feedback", {})[f"{session_id}-{index}"] = "up"
        st.toast("已记录赞")

    def _do_down() -> None:
        st.session_state.setdefault("kb_feedback", {})[f"{session_id}-{index}"] = "down"
        st.toast("已记录踩")

    def _do_regen() -> None:
        sessions = _kb_sessions()
        history = sessions[session_id]["messages"][:index]
        user_msg = _last_user_question(history)
        if user_msg:
            _send_kb_question(user_msg)
        else:
            st.toast("未找到上一条用户提问")

    def _do_more() -> None:
        st.toast("更多操作待扩展")

    actions = [
        (":material/content_copy:", "复制", f"copy-{session_id}-{index}", _do_copy),
        (":material/thumb_up:", "赞", f"up-{session_id}-{index}", _do_up),
        (":material/thumb_down:", "踩", f"down-{session_id}-{index}", _do_down),
        (":material/refresh:", "重新生成", f"regen-{session_id}-{index}", _do_regen),
        (":material/more_horiz:", "更多", f"more-{session_id}-{index}", _do_more),
    ]
    n_citations = len(citations) if citations else 0
    # 动态列宽：5 个操作按钮 + 1 个引用按钮（有引用时）+ 剩余空白
    col_widths = [0.07] * 5
    if n_citations:
        col_widths.append(0.07)
    remaining = max(0.07, 1.0 - sum(col_widths))
    col_widths.append(remaining)

    action_key = f"kb_msg_actions_{session_id}_{index}"
    with st.container(key=action_key):
        cols = st.columns(col_widths, gap="small")
        for col, (icon, label, key, handler) in zip(cols[:5], actions):
            with col:
                if st.button(
                    "",
                    icon=icon,
                    help=label,
                    key=key,
                    use_container_width=True,
                ):
                    handler()
        # 有引用时放一个 📚 图标按钮，点击在右侧展开所有引用
        if n_citations:
            with cols[5]:
                clicked = st.button(
                    "",
                    icon=":material/library_books:",
                    key=f"cite-sources-{session_id}-{index}",
                    help=f"查看全部 {n_citations} 个引用来源",
                )
                if clicked:
                    st.session_state["_kb_active_citation_msg_idx"] = index
                    st.rerun()


def _render_kb_sources_panel() -> None:
    """右侧引用来源面板：点击消息下方 📚 图标时展开对应消息的所有引用。"""
    st.markdown('<div class="kb-sources-panel">', unsafe_allow_html=True)

    active_idx = st.session_state.get("_kb_active_citation_msg_idx")
    citation_messages = st.session_state.get("_kb_citation_messages", {})

    if active_idx is None or active_idx not in citation_messages:
        st.markdown("#### 📚 引用来源")
        st.caption("点击回答下方的 📚 图标查看引用详情")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # 关闭按钮（仅 ✕）+ 标题，同行右对齐
    close_col, title_col = st.columns([0.08, 0.92])
    with close_col:
        if st.button("✕", key="kb-close-sources"):
            st.session_state["_kb_active_citation_msg_idx"] = None
            st.rerun()
    with title_col:
        st.markdown(f"#### 📚 引用来源（消息 {active_idx + 1}）")

    citations = citation_messages[active_idx]
    for cite_index, citation in enumerate(citations, start=1):
        title = citation.get("title", "") or "未命名来源"
        location = citation.get("location", "")
        detail = citation.get("content") or citation.get("snippet", "")
        label_parts = [f"{cite_index}. {html.escape(title)}"]
        if location:
            label_parts.append(f"（{html.escape(location)}）")
        with st.expander("  ".join(label_parts), expanded=False):
            if detail:
                st.markdown(
                    f'<div style="font-size:0.9rem;line-height:1.75;color:#374151;">'
                    f'{html.escape(detail).replace(chr(10), "<br>")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("暂无详细内容")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_kb_manager(kb: CourseKnowledgeBase) -> None:
    st.markdown('<div class="section-title">知识库</div>', unsafe_allow_html=True)
    st.markdown("#### 当前内容")
    st.caption(_kb_doc_summary(kb))

    if st.button(
        "清空知识库",
        key="kb-clear",
        use_container_width=True,
        type="secondary",
    ):
        kb_store.clear()
        st.session_state["kb_qa_base"] = CourseKnowledgeBase()
        st.success("知识库已清空，所有导入的教材已从本地存储删除。")
        st.rerun()

    st.markdown("#### 从 GitHub 导入")
    gh_url = st.text_input(
        "GitHub 仓库地址",
        placeholder="https://github.com/owner/repo",
        key="kb_gh_url",
        label_visibility="collapsed",
    )
    if st.button("导入仓库", key="kb-gh-import", use_container_width=True):
        if not gh_url.strip():
            st.warning("请先输入 GitHub 仓库地址。")
        else:
            try:
                with st.spinner("正在拉取仓库并分块..."):
                    added = kb.load_github_repo(gh_url.strip())
                kb_store.save_chunks(kb.chunks)
                # 解析 owner/repo 作为默认学习主题，提示用户一键生成计划
                from edu_agent.tools.github_importer import _parse_repo_url

                try:
                    owner, repo = _parse_repo_url(gh_url.strip())
                    repo_label = f"{owner}/{repo}"
                except Exception:  # noqa: BLE001
                    repo_label = gh_url.strip()
                st.session_state["_kb_last_import"] = repo_label
                st.session_state["form_topic"] = f"学习 {repo_label}"
                st.session_state["form_level"] = "零基础"
                st.session_state["form_days"] = 14
                st.session_state["form_daily_time"] = "1.5 小时"
                st.session_state["form_goal"] = f"基于导入了 {added} 块的仓库 {repo_label} 生成学习计划"
                st.success(f"已从 GitHub 导入 {repo_label}（{added} 块），主题已预填，切到「学习计划」tab 一键生成。")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - 导入失败给出可读提示
                st.error(f"导入失败：{exc}")
    st.markdown("#### 导入教材文件")
    uploaded = st.file_uploader(
        "导入教材文件（.md / .txt）",
        type=["md", "txt"],
        key="kb_upload",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        try:
            text = uploaded.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001 - 文件读取失败给出提示
            st.error(f"读取文件失败：{exc}")
        else:
            if text.strip():
                added = kb.load_markdown(uploaded.name, text.strip())
                kb_store.save_chunks(kb.chunks)
                st.session_state.pop("kb_upload", None)
                st.success(f"已导入《{uploaded.name}》，新增 {added} 个知识块。")
                st.rerun()
            else:
                st.warning("文件内容为空。")
    st.markdown("#### 追加教材（Markdown）")
    extra_text = st.text_area(
        "追加内容",
        placeholder="# 新章节\n\n## 小节\n\n正文内容...",
        height=120,
        key="kb_extra_text",
        label_visibility="collapsed",
    )
    if st.button("加入知识库", key="kb-append", use_container_width=True):
        if extra_text.strip():
            added = kb.load_markdown("我的补充.md", extra_text.strip())
            kb_store.save_chunks(kb.chunks)
            st.session_state["kb_extra_text"] = ""
            st.success(f"已加入 {added} 个知识块，可以直接提问了。")
            st.rerun()
        else:
            st.warning("请先粘贴 Markdown 内容。")


def _render_kb_sidebar(kb: CourseKnowledgeBase) -> None:
    with st.sidebar:
        if st.button(
            "← 返回工作流中心",
            key="kb-back-to-center",
            use_container_width=True,
        ):
            _set_app_screen("workflow_center")
            st.rerun()
        st.divider()
        if st.button("新建对话", key="kb-new-session", use_container_width=True):
            _kb_create_session()
            st.rerun()

        sessions = _kb_sessions()
        if sessions:
            titles = {sid: item["title"] for sid, item in sessions.items()}
            selected = st.radio(
                "会话列表",
                list(sessions),
                format_func=lambda sid: titles[sid],
                label_visibility="collapsed",
                key="kb_session_radio",
            )
            st.session_state["kb_active_session"] = selected
            if st.button("删除当前对话", key="kb-del-session", use_container_width=True):
                del sessions[selected]
                if sessions:
                    st.session_state["kb_active_session"] = next(iter(sessions))
                else:
                    _kb_create_session()
                _persist_kb_sessions()
                st.rerun()
        st.divider()
        _render_kb_manager(kb)


def _render_kb_qa_page(engine: str = "kb_qa") -> None:
    _kb_migrate_legacy_history()
    _render_kb_sidebar(_kb_instance())
    kb = _kb_instance()
    doc_count = len({c.doc_title for c in kb.chunks})

    # 学习者状态摘要（来自本地 SQLite Learner Model，EduAgents 唯一画像真值）
    learner_state = _learner_state_bundle()
    course_state = learner_state.course_state
    mastered_count = sum(1 for k in course_state.knowledge if k.mastery >= 0.7)
    weak_count = sum(1 for k in course_state.knowledge if k.mastery < 0.3)
    kb_col, state_col, hint_col = st.columns([0.42, 0.30, 0.28])
    with kb_col:
        st.caption(f"知识库 · {len(kb.chunks)} 块 · {doc_count} 个文档")
    with state_col:
        st.caption(
            f"画像 v{course_state.state_version or '-'} · 进度 {course_state.progress:.0%}"
            f" · 已掌握 {mastered_count} · 薄弱 {weak_count}"
        )
    with hint_col:
        st.caption(f"本地画像 · {course_state.course_id}")

    # 导入完成提示：banner 引导用户到学习计划 tab
    if st.session_state.get("_kb_last_import"):
        last = st.session_state["_kb_last_import"]
        st.info(
            f"✅ 已导入 **{last}**（{len(kb.chunks)} 块）。"

            " 主题已自动填入下方「学习计划」tab，"
            "点 **生成学习规划** 即可用此知识库生成计划。"
        )

    tab_chat, tab_plan = st.tabs(["💬 知识库问答", "📝 学习计划"])
    with tab_chat:
        # 仅当有激活的引用消息时才显示右侧来源面板；关闭后整个右侧列消失
        active_idx = st.session_state.get("_kb_active_citation_msg_idx")
        citation_messages = _collect_citation_messages()
        if active_idx is not None and active_idx in citation_messages:
            chat_col, source_col = st.columns([0.72, 0.28])
            with chat_col:
                _render_kb_chat(kb, engine)
            with source_col:
                with st.container(key="kb_source_col"):
                    _render_kb_sources_panel()
        else:
            _render_kb_chat(kb, engine)
    with tab_plan:
        _render_study_plan_tab()


def _render_study_plan_tab() -> None:
    """与知识库问答整合在同一页面：表单 + 一键生成，结果原地展示。"""
    from edu_agent.workflows.study_plan.schemas import StudentInput
    from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow

    st.markdown("#### 学习规划生成器")
    st.caption("把知识库问答中学到的主题，一键生成学习计划。")

    sessions = _kb_sessions()
    active = _kb_active_session_id()
    title = sessions[active]["title"] if sessions else ""
    if title and title != "新对话":
        if st.button(
            f"从当前会话导入主题：「{title}」",
            key="kb-import-to-plan",
            use_container_width=True,
        ):
            st.session_state["form_topic"] = title
            st.session_state["form_level"] = "零基础"
            st.session_state["form_days"] = 14
            st.session_state["form_daily_time"] = "1.5 小时"
            st.session_state["form_goal"] = f"基于知识库会话「{title}」生成学习计划"
            st.rerun()

    with st.form("kb_plan_form"):
        topic = st.text_input(
            "学习主题",
            value=st.session_state.get("form_topic") or "GPT-2 从零实现",
            key="plan_topic",
        )
        level = st.text_area(
            "当前基础",
            value=st.session_state.get("form_level") or "会 Python 基础，但没做过 GPT",
            key="plan_level",
            height=80,
        )
        col_d, col_t = st.columns(2)
        with col_d:
            days = st.number_input(
                "学习周期（天）",
                min_value=1,
                max_value=180,
                value=int(st.session_state.get("form_days") or 14),
                key="plan_days",
            )
        with col_t:
            daily_time = st.text_input(
                "每天学习时间",
                value=st.session_state.get("form_daily_time") or "1.5 小时",
                key="plan_daily_time",
            )
        goal = st.text_area(
            "学习目标",
            value=st.session_state.get("form_goal") or "能独立跑通 build-nanogpt 训练",
            key="plan_goal",
            height=80,
        )
        submitted = st.form_submit_button("生成学习规划", type="primary", use_container_width=True)

    if submitted:
        if not topic.strip() or not level.strip() or not daily_time.strip() or not goal.strip():
            st.warning("请完整填写所有字段。")
        else:
            try:
                # 从知识库检索与主题相关的内容，作为 Planner 的参考资料（没有则"无"）
                hits = _kb_instance().search(topic.strip(), top_k=4)
                if hits:
                    knowledge_context = "\n\n".join(
                        f"[{index}] 《{chunk.doc_title}》 {chunk.heading_path}\n{chunk.text[:800]}"
                        for index, chunk in enumerate(hits, start=1)
                    )
                    st.caption(f"已参考知识库 {len(hits)} 个块生成学习计划。")
                else:
                    knowledge_context = "无"

                # 自适应上下文：读 LearnerState → 决策 → 注入 Planner（画像不可用时为空，不中断）
                from edu_agent.adaptive.service import prepare_adaptive_context

                try:
                    _ctx, _dec, plan_prompt_ctx = prepare_adaptive_context(
                        task_type="study_plan",
                        query=topic.strip(),
                    )
                    learner_context = plan_prompt_ctx.get("learner_context", "")
                    adaptive_instructions = plan_prompt_ctx.get("adaptive_instructions", "")
                except Exception:  # noqa: BLE001
                    learner_context, adaptive_instructions = "", ""

                with st.spinner("正在生成学习规划（多步流水线，可能 1-3 分钟）..."):
                    result = run_study_plan_workflow(
                        StudentInput(
                            topic=topic.strip(),
                            level=level.strip(),
                            days=int(days),
                            daily_time=daily_time.strip(),
                            goal=goal.strip(),
                        ),
                        knowledge_context=knowledge_context,
                        learner_context=learner_context,
                        adaptive_instructions=adaptive_instructions,
                    )
                st.session_state["_kb_plan_result"] = result
                st.session_state["study_plan_result"] = result
                st.session_state["student_input"] = StudentInput(
                    topic=topic.strip(),
                    level=level.strip(),
                    days=int(days),
                    daily_time=daily_time.strip(),
                    goal=goal.strip(),
                )
                _persist_study_plan()
            except Exception as exc:  # noqa: BLE001
                st.error(f"生成失败：{exc}")

    plan_result = st.session_state.get("_kb_plan_result") or st.session_state.get("study_plan_result")
    if plan_result:
        st.divider()
        st.markdown("### 最终学习计划")
        st.markdown(plan_result.get("final_plan", ""))
        st.download_button(
            "下载 Markdown",
            data=plan_result.get("final_plan", ""),
            file_name="study-plan.md",
            mime="text/markdown",
        )


def _render_workflow_center(result: dict | None) -> None:
    screen = st.session_state.get("app_screen", "workflow_center")

    if screen == "kb_qa_chat":
        _render_kb_qa_page(engine="kb_qa")
        return

    if screen == "study_plan_input":
        st.button(
            "返回工作流中心",
            key="back-to-workflow-center",
            icon=":material/arrow_back:",
            on_click=_set_app_screen,
            args=("workflow_center",),
        )
        st.markdown("## 学习规划构建器")
        st.caption("描述学习目标，确认解析结果后生成可执行的学习规划。")
        input_col, form_col = st.columns([0.46, 0.54], gap="large")
        with input_col:
            _render_quick_input()
            with st.container(border=True):
                st.markdown("#### 工作流能力")
                st.write("需求分析、内容拆解、联网检索、资源筛选、自适应决策、计划生成与质量校验。")
                st.caption(
                    f"联网搜索：{_search_status_text()} / 输出格式：Markdown"
                )
        with form_col:
            _render_form()
        return

    st.markdown("# 工作流中心")
    st.caption("选择一个教育工作流，完成从需求输入到结构化结果的全过程。")
    active_col, future_col = st.columns([0.62, 0.38], gap="large")
    with active_col:
        st.markdown('<div class="section-title">当前可用</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("### 学习规划")
            st.write(
                "根据学习主题、当前基础、学习周期、每日时间和目标，生成结构化、可执行、可检查的学习计划。"
            )
            feature_a, feature_b, feature_c = st.columns(3)
            feature_a.metric("工作阶段", "8 个", border=False)
            feature_b.metric("联网搜索", _search_status_text(), border=False)
            feature_c.metric("输出", "Markdown", border=False)
            if result is None:
                st.button(
                    "启动学习规划",
                    key="launch-study-plan",
                    type="primary",
                    use_container_width=True,
                    on_click=_set_app_screen,
                    args=("study_plan_input",),
                )
            else:
                open_col, new_col = st.columns(2)
                open_col.button(
                    "打开当前工作台",
                    key="open-current-workbench",
                    type="primary",
                    use_container_width=True,
                    on_click=_set_app_screen,
                    args=("workbench",),
                )
                new_col.button(
                    "新建学习规划",
                    key="create-new-study-plan",
                    use_container_width=True,
                    on_click=_set_app_screen,
                    args=("study_plan_input",),
                )
            st.divider()
            st.markdown("### 知识库问答")
            st.write(
                "结合知识库内容生成口语化、分步骤回答，涉及知识点自动附来源引用；"
                "知识库未覆盖时明确引导进入学情诊断，不编造内容；平台异常时自动降级为本地检索回答。"
            )
            kb_feature_a, kb_feature_b, kb_feature_c = st.columns(3)
            kb_feature_a.metric("来源引用", "自动", border=False)
            kb_feature_b.metric("AI 标识", "合规", border=False)
            kb_feature_c.metric("失败降级", "本地兜底", border=False)
            st.button(
                "启动知识库问答",
                key="launch-kb-qa",
                type="primary",
                use_container_width=True,
                on_click=_set_app_screen,
                args=("kb_qa_chat",),
            )

    with future_col:
        st.markdown('<div class="section-title">后续工作流</div>', unsafe_allow_html=True)
        with st.container(border=True):
            future_workflows = [
                ("错题反思", "分析错误原因并形成针对性改进建议"),
                ("学情报告", "汇总学习状态并生成阶段学习报告"),
                ("课程问答", "结合课程资料进行上下文问答"),
                ("迁移学习", "跨课程知识类比（如 Java→Python）"),
            ]
            for index, (name, description) in enumerate(future_workflows):
                if index:
                    st.divider()
                st.markdown(f"**{name}**")
                st.caption(description)


def _render_workbench_header(student_input: StudentInput) -> None:
    back_col, title_col, action_col = st.columns([0.18, 0.47, 0.35], gap="small")
    with back_col:
        st.button(
            "工作流中心",
            key="workbench-back",
            icon=":material/arrow_back:",
            on_click=_set_app_screen,
            args=("workflow_center",),
        )
    with title_col:
        st.markdown('<div class="workbench-context">学习规划</div>', unsafe_allow_html=True)
        topic_text = student_input.topic if student_input else "未指定主题"
        st.markdown(
            f'<div class="workbench-topic">{html.escape(topic_text)}</div>',
            unsafe_allow_html=True,
        )
    with action_col:
        ai_col, process_col = st.columns(2)
        ai_col.button(
            "AI 助教",
            key="open-ai-assistant",
            icon=":material/psychology:",
            use_container_width=True,
            on_click=_open_aux_panel,
            args=("ai",),
        )
        process_col.button(
            "运行过程",
            key="open-process-details",
            icon=":material/account_tree:",
            use_container_width=True,
            on_click=_open_aux_panel,
            args=("process",),
        )


def _render_product_header() -> None:
    st.markdown(
        """
        <div class="product-header">
            <div class="product-name">教育智能体</div>
            <div class="product-subtitle">教育工作流平台</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("AI 助教", width="large", on_dismiss=_close_aux_panel)
def _render_ai_assistant_dialog(
    result: dict,
    student_input: StudentInput,
    knowledge_map: KnowledgeMap,
) -> None:
    selected = _selected_knowledge_node(knowledge_map)
    knowledge_scope = st.session_state.get("workbench_view") == "知识学习"
    history_key = selected.id if knowledge_scope else "__plan__"
    if knowledge_scope:
        st.caption(
            f"知识点独立会话：{knowledge_map.topic} / {selected.category} / {selected.title}"
        )
    else:
        st.caption(f"学习计划会话：{knowledge_map.topic}")

    all_histories = st.session_state.setdefault("knowledge_chat_histories", {})
    history_data = all_histories.setdefault(history_key, [])
    if not history_data:
        if knowledge_scope:
            st.info("这个会话只保存当前知识点的问答，不会和其他知识点混在一起。")
        else:
            st.info("可以询问学习顺序、时间安排，或者如何调整整份学习计划。")
    for message in history_data:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    suggested = (
        [
            f"解释一下「{selected.title}」",
            f"「{selected.title}」和它的前置知识有什么关系？",
            f"如何检查我是否掌握「{selected.title}」？",
        ]
        if knowledge_scope
        else [
            "我现在应该先学习什么？",
            "每天时间不够时如何调整？",
            "如何检查整份计划是否完成？",
        ]
    )
    question = None
    suggestion_columns = st.columns(3)
    for column, suggestion in zip(suggestion_columns, suggested):
        if column.button(
            suggestion,
            key=f"dialog-suggest-{suggestion}",
            use_container_width=True,
        ):
            question = suggestion

    with st.form("plan-chat-dialog-form", clear_on_submit=True):
        typed_question = st.text_input(
            "继续提问",
            placeholder="围绕当前学习计划或知识点提问",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("发送", type="primary")
    if submitted:
        question = typed_question.strip()

    if question:
        history_data.append({"role": "user", "content": question})
        try:
            with st.spinner("正在结合当前计划回答..."):
                # 自适应上下文（plan_chat：计划调整 + 画像）
                from edu_agent.adaptive.service import prepare_adaptive_context

                try:
                    _ctx, _dec, _chat_ctx = prepare_adaptive_context(
                        task_type="plan_chat",
                        query=question,
                    )
                    chat_learner_context = _chat_ctx.get("learner_context", "")
                except Exception:  # noqa: BLE001
                    chat_learner_context = ""
                answer = answer_plan_question(
                    question=question,
                    student_input=student_input,
                    final_plan=result["final_plan"],
                    history=[ChatTurn(**item) for item in history_data[:-1]],
                    selected_topic=selected if knowledge_scope else None,
                    resources=result["evaluated_research"].resources,
                    learner_context=chat_learner_context,
                )
            answer_parts = [answer.answer_markdown]
            if answer.citations:
                answer_parts.extend(["", "**参考资源**", _list_to_markdown(answer.citations)])
            if answer.plan_change_suggested and answer.plan_change_summary:
                answer_parts.extend(["", f"**计划调整建议：** {answer.plan_change_summary}"])
            history_data.append(
                {"role": "assistant", "content": "\n".join(answer_parts)}
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - keep the dialog usable
            st.error(f"回答失败：{exc}")

    if st.button("关闭", key="close-ai-assistant"):
        _close_aux_panel()
        st.rerun(scope="app")


@st.dialog("运行过程", width="large", on_dismiss=_close_aux_panel)
def _render_process_dialog(result: dict) -> None:
    st.caption("以下为本次学习规划完成后保留的各阶段结果，不模拟实时执行进度。")
    _render_process_details(result)
    if st.button("关闭", key="close-process-details"):
        _close_aux_panel()
        st.rerun(scope="app")


st.set_page_config(page_title="教育智能体", layout="wide")

st.markdown(
    """
    <style>
    .stAppViewContainer {
        background: #f7f8fb;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }
    .block-container {
        max-width: 1240px;
        padding-top: 5.25rem;
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
        background: #ffffff;
    }
    div[data-testid="stMetric"] {
        padding: 0.35rem 0;
        background: transparent;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dfe3ea;
        border-radius: 10px;
        background: #ffffff;
    }
    .section-title {
        margin: 0.9rem 0 0.7rem;
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
    .product-header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 990;
        display: flex;
        align-items: baseline;
        gap: 0.8rem;
        min-height: 3.75rem;
        box-sizing: border-box;
        padding: 1.05rem max(1rem, calc((100vw - 1240px) / 2));
        margin: 0;
        border-bottom: 1px solid #e1e5ec;
        background: rgba(255, 255, 255, 0.96);
        backdrop-filter: blur(8px);
    }
    .product-name {
        color: #1659b7;
        font-size: 1.25rem;
        font-weight: 780;
        line-height: 1.2;
    }
    .product-subtitle {
        color: #7a8494;
        font-size: 0.82rem;
        font-weight: 550;
    }
    .workbench-context {
        color: #64748b;
        font-size: 0.78rem;
        font-weight: 650;
        margin-top: 0.1rem;
    }
    .workbench-topic {
        color: #172033;
        font-size: 1.08rem;
        font-weight: 750;
        line-height: 1.35;
        margin-top: 0.15rem;
        overflow-wrap: anywhere;
    }
    div[data-testid="stDialog"] div[role="dialog"] {
        border-radius: 10px;
    }
    .st-key-knowledge-path {
        overflow-x: auto;
        padding: 0.2rem 0 0.8rem;
        scrollbar-width: thin;
    }
    .st-key-knowledge-path div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap;
        width: max-content;
        min-width: 100%;
    }
    .st-key-knowledge-path .stButton {
        flex: 0 0 190px;
        width: 190px;
    }
    .st-key-knowledge-path .stButton button {
        width: 190px;
        min-height: 58px;
        justify-content: flex-start;
        text-align: left;
        padding: 0.65rem 0.75rem;
    }
    .st-key-knowledge-path .stButton button p {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 0.86rem;
    }
    div[role="radiogroup"] label {
        padding: 0.55rem 0.65rem;
        border-radius: 6px;
    }
    div[role="radiogroup"] label:hover {
        background: #f6f8fb;
    }
    div[data-testid="stChatMessage"] {
        display: none !important;
    }

    /* GPT 风格聊天消息：整页滚动（页面滚），底部给固定输入框留空间 */
    .kb-chat-messages {
        max-width: 48rem;
        margin: 0 auto;
        padding: 0.5rem 1rem 6.5rem;  /* 底部 6.5rem 让最后一条消息在输入框上方 */
    }
    .chat-msg {
        display: flex;
        width: 100%;
        margin: 0.25rem 0;
    }
    .chat-msg.user-msg {
        justify-content: flex-end;
    }
    .chat-msg.ai-msg {
        justify-content: flex-start;
    }
    .user-bubble {
        background: #f2f2f2;
        color: #1f2937;
        padding: 0.45rem 0.95rem;
        border-radius: 1.25rem;
        max-width: 80%;
        font-size: 0.98rem;
        line-height: 1.55;
        word-wrap: break-word;
        margin: 0.35rem 0;
    }
    .ai-content {
        width: 100%;
        max-width: 48rem;
        color: #1f2937;
        font-size: 1rem;
        line-height: 1.7;
        padding: 0.35rem 0;
    }
    .ai-content p {
        margin: 0.6rem 0;
    }
    .ai-content pre {
        background: #f6f8fa;
        border-radius: 8px;
        padding: 0.85rem;
        overflow-x: auto;
    }
    .ai-content code {
        font-family: "SF Mono", "Menlo", "Consolas", monospace;
        font-size: 0.9em;
    }

    /* GPT 风格操作图标行 */
    [class*="st-key-kb_msg_actions_"] {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        margin: 0.4rem 0 0.9rem;  /* 别再往上压 */
        max-width: 48rem;
    }
    [class*="st-key-kb_msg_actions_"] .stHorizontalBlock {
        gap: 0.25rem !important;
    }
    [class*="st-key-kb_msg_actions_"] .stButton {
        flex: 0 0 auto !important;
        width: auto !important;
    }
    [class*="st-key-kb_msg_actions_"] .stButton > button {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #4b5563 !important;  /* 默认深一些，浅灰在白底上几乎看不见 */
        padding: 0.3rem 0.5rem !important;
        min-width: 32px !important;
        min-height: 32px !important;
        border-radius: 6px !important;
        font-size: 0.9rem !important;
    }
    [class*="st-key-kb_msg_actions_"] .stButton > button:hover {
        background: #f3f4f6 !important;
        color: #111827 !important;
        border-color: #e5e7eb !important;
    }
    [class*="st-key-kb_msg_actions_"] .stButton > button:active {
        background: #e5e7eb !important;
    }
    [class*="st-key-kb_msg_actions_"] [data-testid="stCaptionContainer"] {
        color: #9ca3af;
        font-size: 0.75rem;
        margin-left: auto;
        padding-left: 0.5rem;
    }

    /* 右侧引用来源列：sticky 在视口上方，跟随滚动始终可见 */
    /* 右侧引用来源列（keyed container）：sticky 跟随视口，滚动聊天时始终可见 */
    [class*="st-key-kb_source_col"] {
        position: sticky;
        top: 1rem;
        align-self: flex-start;  /* 让 sticky 相对视口生效，不随左列高度撑开 */
    }
    /* 右侧引用来源面板：固定高度、可滚动 */
    .kb-sources-panel {
        max-height: calc(100vh - 120px);
        overflow-y: auto;
        padding-right: 0.5rem;
    }

    /* 澄清方向按钮 */
    .clarify-prompt {
        max-width: 48rem;
        margin: 0.75rem auto 0.5rem;
        color: #4b5563;
        font-size: 0.95rem;
    }

    /* 底部输入区：只剩 chat_input（disclaimer 已删除），更紧凑 */
    .st-key-kb_input_footer {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #ffffff;
        padding: 0.4rem 1rem 0.6rem;  /* 只包输入框，padding 极简 */
        z-index: 1000;
        box-shadow: 0 -4px 16px rgba(0,0,0,0.06);
    }
    div[data-testid="stChatInput"] {
        max-width: 48rem;
        margin: 0 auto;
        border: 1px solid #e5e7eb;
        border-radius: 24px;
        padding: 0.2rem 0.75rem;  /* chat_input 自身垂直 padding 收紧 */
        background: #ffffff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    div[data-testid="stChatInput"] textarea {
        border-radius: 20px;
        font-size: 0.98rem;
        color: #1f2937;
    }
    div[data-testid="stChatInput"]::before {
        background: transparent !important;
    }
    div[data-testid="stChatInput"] button {
        color: #2563eb;
    }
    .stButton > button {
        font-size: 0.78rem !important;
        padding: 0.2rem 0.55rem !important;
        height: auto !important;
        min-height: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

result = st.session_state.get("study_plan_result")
last_input = st.session_state.get("student_input")

# 启动时从磁盘恢复关键状态（仅在 session_state 缺失时填充）
_load_persisted_state()

result = st.session_state.get("study_plan_result")
last_input = st.session_state.get("student_input")

_render_product_header()

if "app_screen" not in st.session_state:
    st.session_state["app_screen"] = "workbench" if result is not None else "workflow_center"
if st.session_state["app_screen"] == "workbench" and (result is None or last_input is None):
    # 数据不一致：result 存在但 student_input 缺失（如旧会话残留 / 字段被清），
    # 直接回工作流中心，避免 workbench 渲染时访问 None.topic 崩溃。
    st.session_state["app_screen"] = "workflow_center"

if st.session_state["app_screen"] != "workbench" or result is None:
    _render_workflow_center(result)
else:
    _render_workbench_header(last_input)
    with st.expander("调整学习需求并重新生成", expanded=False):
        _render_quick_input()
        _render_form()

    knowledge_map = build_knowledge_map(last_input, result["decomposition"])
    result["knowledge_map"] = knowledge_map
    view_names = ["学习概览", "知识学习", "学习画像", "完整计划"]
    if st.session_state.get("workbench_view") not in view_names:
        st.session_state["workbench_view"] = "学习概览"
    selected_view = st.segmented_control(
        "工作台视图",
        view_names,
        label_visibility="collapsed",
        key="workbench_view",
        on_change=_handle_workbench_view_change,
    ) or "学习概览"

    if selected_view == "学习概览":
        _render_learning_overview(result, last_input, knowledge_map)
    elif selected_view == "知识学习":
        _render_knowledge_map(result, last_input, knowledge_map)
    elif selected_view == "学习画像":
        _render_learner_state_panel()
    else:
        _render_final_plan(result)

    active_aux_panel = st.session_state.get("active_aux_panel")
    if active_aux_panel == "ai":
        _render_ai_assistant_dialog(result, last_input, knowledge_map)
    elif active_aux_panel == "process":
        _render_process_dialog(result)
