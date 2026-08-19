import time
from typing import Any, Callable, Dict, Optional

from edu_agent.workflows.study_plan.agents import (
    analyzer_agent,
    decomposer_agent,
    planner_agent,
    resource_evaluator_agent,
    researcher_agent,
    reviewer_agent,
)
from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map
from edu_agent.workflows.study_plan.schemas import (
    AnalysisResult,
    DecompositionResult,
    DraftPlan,
    EvaluatedResearchResult,
    EvaluatedResource,
    KnowledgeMap,
    LearningStageSuggestion,
    PlanValidationResult,
    ResearchResult,
    ReviewResult,
    StudentInput,
)
from edu_agent.workflows.study_plan.validator import validate_study_plan


def _run_step(step_name: str, func: Callable[..., Any], fallback: Callable[[Exception], Any], *args):
    """执行流水线一步，并在控制台打印开始/完成/失败日志（用于诊断卡在哪一步）。"""
    start = time.time()
    print(f"[study_plan] ▶ 开始步骤: {step_name}", flush=True)
    try:
        result = func(*args)
        print(
            f"[study_plan] ✓ {step_name} 完成，耗时 {time.time() - start:.1f}s",
            flush=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001 - workflow should return displayable errors
        print(
            f"[study_plan] ✗ {step_name} 失败（{time.time() - start:.1f}s）: {exc} → 走降级",
            flush=True,
        )
        return fallback(exc)


def _fallback_analysis(student_input: StudentInput, exc: Exception) -> AnalysisResult:
    # 降级只使用学生输入（topic / level / goal），不泄漏内部异常或 Agent 名称。
    return AnalysisResult(
        topic=student_input.topic,
        level_summary=student_input.level or "（未提供，按首次学习处理）",
        goal_summary=student_input.goal,
        prerequisites=["根据学习主题补充必要基础知识", "准备可运行的学习环境"],
        need_web_search=False,
        search_queries=[],
    )


def _fallback_research(exc: Exception) -> ResearchResult:
    # 降级不泄漏异常文本；只说明将基于学生输入生成。
    return ResearchResult(
        search_enabled=False,
        summary="将只基于学生输入生成学习规划。",
        key_points=[],
        resources=[],
    )


def _fallback_decomposition(
    student_input: StudentInput,
    analysis: AnalysisResult,
    exc: Exception,
) -> DecompositionResult:
    topic = analysis.topic or student_input.topic
    prerequisites = analysis.prerequisites or [f"{topic} 的前置知识", "可运行的学习环境"]
    core = [
        f"{topic} 的核心概念和术语",
        f"{topic} 的基本操作流程",
        f"{topic} 学习目标对应的交付产出",
    ]
    applications = [
        f"完成一个和 {topic} 直接相关的小案例",
        "每天保留笔记、代码、截图或讲解记录作为检查证据",
    ]
    # Compatibility fallback derives a conservative sparse prerequisite chain
    # from legacy learning_sequence when explicit ConceptSpec relations are
    # unavailable. learning_sequence 由真实概念标题组成（前置→核心→应用），
    # 以便构建稀疏依赖链（A→B→C→D），而非 complete-bipartite dense graph。
    return DecompositionResult(
        core_concepts=core,
        prerequisite_concepts=prerequisites,
        learning_sequence=prerequisites + core + applications,
        difficulty_points=[
            f"{topic} 范围可能过宽，需要聚焦当前周期主线",
            "每日任务需要有明确产出，否则难以检查进度",
        ],
        stages=[
            LearningStageSuggestion(
                stage_id="stage-1", title="基础准备",
                objective=f"补齐 {topic} 前置知识和环境", order=1,
            ),
            LearningStageSuggestion(
                stage_id="stage-2", title="核心学习",
                objective=f"完成 {topic} 主题主线学习与最小应用案例", order=2,
            ),
            LearningStageSuggestion(
                stage_id="stage-3", title="综合应用",
                objective="完成作品、验收和复盘", order=3,
            ),
        ],
        application_directions=applications + ["内容拆解步骤使用降级模板生成"],
    )


def _fallback_evaluated_research(
    research: ResearchResult,
    exc: Exception,
) -> EvaluatedResearchResult:
    resources = [
        EvaluatedResource(
            title=resource.title,
            url=resource.url,
            summary=resource.summary,
            source_type="unknown",
            quality_score=3,
            reason="资源评估步骤未完成，已保留 Researcher 原始结果供 Planner 参考。",
            suitable_stage="按学习阶段需要使用",
        )
        for resource in research.resources
    ]
    return EvaluatedResearchResult(
        search_enabled=research.search_enabled,
        summary="已使用 Researcher 原始结果降级。",
        key_points=research.key_points,
        resources=resources if research.search_enabled else [],
    )


def _fallback_draft(
    student_input: StudentInput,
    analysis: AnalysisResult,
    research: ResearchResult,
    decomposition: DecompositionResult,
    evaluated_research: EvaluatedResearchResult,
    exc: Exception,
) -> DraftPlan:
    topic = analysis.topic or student_input.topic
    daily_rows = []
    sequence = decomposition.learning_sequence or decomposition.core_concepts or [topic]
    for day in range(1, student_input.days + 1):
        concept = sequence[(day - 1) % len(sequence)]
        daily_rows.append(
            f"| 第 {day} 天 | {concept} | 整理 3 条概念笔记并标出 1 个疑问 | "
            f"完成一个与「{concept}」相关的最小应用案例 | 提交笔记、案例结果和疑问记录 | {student_input.daily_time} |"
        )

    stage_rows = []
    stages = decomposition.stages or []
    stage_list = [
        (s.title, s.objective) for s in sorted(stages, key=lambda s: s.order)
    ] or [("基础准备", "补齐前置知识和环境"), ("核心学习", "完成主线学习与最小案例"), ("综合应用", "完成作品与复盘")]
    for index, (stage_title, stage_objective) in enumerate(stage_list[:3], start=1):
        start_day = max(1, round((index - 1) * student_input.days / max(len(stage_list[:3]), 1)) + 1)
        end_day = max(start_day, round(index * student_input.days / max(len(stage_list[:3]), 1)))
        stage_rows.append(
            f"| 阶段 {index} | 第 {start_day}-{end_day} 天 | {stage_title}（{stage_objective}） | "
            "提交阶段应用案例、问题清单和复盘记录 |"
        )

    if evaluated_research.resources:
        resource_rows = [
            f"| {resource.source_type} | [{resource.title}]({resource.url}) | {resource.reason} | {resource.suitable_stage} |"
            if resource.url
            else f"| {resource.source_type} | {resource.title} | {resource.reason} | {resource.suitable_stage} |"
            for resource in evaluated_research.resources[:5]
        ]
    else:
        resource_rows = [
            "| 官方文档 | 按学习主题自行检索官方资料 | 查证概念、术语和接口说明 | 概念查证阶段 |",
            "| 入门教程 | 选择一份与当前目标匹配的教程 | 跟随完成最小示例 | 基础阶段 |",
            "| 实践项目 | 选择一个小型案例 | 用于最终综合产出 | 实践阶段 |",
        ]

    markdown = f"""# {topic} 学习规划

> 初版计划由降级模板生成。

## 一、计划摘要

| 项目 | 内容 |
| -- | -- |
| 学习主题 | {topic} |
| 学习周期 | {student_input.days} 天 |
| 每天学习时间 | {student_input.daily_time} |
| 当前基础 | {analysis.level_summary} |
| 最终目标 | {student_input.goal} |
| 联网资料 | {"已启用" if research.search_enabled else "未启用"} |

## 二、学习内容拆解

### 1. 前置知识

{chr(10).join(f"- {item}" for item in decomposition.prerequisite_concepts)}

### 2. 核心知识点

{chr(10).join(f"- {item}" for item in decomposition.core_concepts)}

### 3. 推荐学习顺序

{chr(10).join(f"- {item}" for item in decomposition.learning_sequence)}

### 4. 可能难点

{chr(10).join(f"- {item}" for item in decomposition.difficulty_points)}

## 三、学习路线概览

- 先用前置知识和环境检查降低启动成本，确保后续任务能实际提交。
- 围绕核心知识点安排每日学习和最小应用案例，避免把旁支内容挤进主线。
- 每个阶段都提交可检查产出，用问题清单驱动下一天调整。
- 最后用综合任务对照学习目标完成验收。

## 四、阶段安排

| 阶段 | 时间 | 学习重点 | 阶段产出 |
| -- | -- | -- | -- |
{chr(10).join(stage_rows)}

## 五、每日学习计划

| 天数 | 学习主题 | 学习任务 | 实践任务 | 检查方式 | 预计时间 |
| -- | -- | -- | -- | -- | -- |
{chr(10).join(daily_rows)}

## 六、推荐资源

| 类型 | 资源 | 用途 | 适合阶段 |
| -- | -- | -- | -- |
{chr(10).join(resource_rows)}

## 七、最终验收标准

- 能独立说明 {topic} 的核心概念、使用场景和常见限制。
- 能提交覆盖每日任务的笔记、案例结果和问题清单。
- 能完成一个和学习目标直接相关的综合作品或案例。
- 能用自检清单指出 2 个薄弱点和下一步修正动作。

## 八、执行建议

- 每天结束前用 5 分钟记录“完成产出、卡点、明日动作”。
- 遇到卡点时先缩小问题范围，保留错误信息或过程截图，再查资料。
- 如果当天任务超过 {student_input.daily_time}，优先保留主线任务，把拓展内容移到复盘后处理。
"""
    return DraftPlan(plan_markdown=markdown)


def _fallback_validation(exc: Exception) -> PlanValidationResult:
    return PlanValidationResult(
        passed=False,
        issues=["规则校验步骤未完成，请人工检查计划章节、每日天数、任务量、应用任务和资源链接。"],
        suggestions=["请人工检查计划章节、每日天数、任务量、应用任务和资源链接。"],
        checked_rules=[],
    )


def _fallback_review(draft_plan: DraftPlan, exc: Exception) -> ReviewResult:
    # 降级不泄漏内部 Agent 名称或异常文本，只说明已返回初版计划。
    return ReviewResult(
        review_summary="已直接返回初版计划，请人工确认任务量和资源推荐是否合适。",
        problems_found=["未完成 LLM 自动审查，请人工确认任务量和资源推荐是否合适。"],
        final_plan_markdown=draft_plan.plan_markdown,
    )


def run_study_plan_workflow(
    student_input: StudentInput,
    knowledge_context: str = "无",
    plan_context: Optional[dict] = None,
) -> dict:
    """学习规划主工作流。

    knowledge_context：知识库参考资料文本（可为"无"）。
    plan_context：PlanContext dict（known/unknown/review/background/style），
                  在 Analyzer/Decomposer/Planner 前生效（生成前就决定跳过/复习/重点）。
    """
    learner_context = _plan_context_to_text(plan_context) if plan_context else ""
    adaptive_instructions = _plan_context_instructions(plan_context) if plan_context else ""

    workflow_start = time.time()
    print(
        f"[study_plan] 开始生成学习计划: topic={student_input.topic!r} "
        f"days={student_input.days} 知识库参考={'有' if knowledge_context and knowledge_context != '无' else '无'} "
        f"自适应上下文={'有' if learner_context else '无'}",
        flush=True,
    )
    analysis = _run_step(
        "analysis",
        analyzer_agent,
        lambda exc: _fallback_analysis(student_input, exc),
        student_input,
        learner_context,
    )
    decomposition = _run_step(
        "decomposition",
        decomposer_agent,
        lambda exc: _fallback_decomposition(student_input, analysis, exc),
        student_input,
        analysis,
        learner_context,
    )
    knowledge_map: KnowledgeMap = build_knowledge_map(student_input, decomposition)
    research = _run_step("research", researcher_agent, _fallback_research, analysis)
    evaluated_research = _run_step(
        "evaluated_research",
        resource_evaluator_agent,
        lambda exc: _fallback_evaluated_research(research, exc),
        research,
        decomposition,
    )
    draft_plan = _run_step(
        "draft_plan",
        planner_agent,
        lambda exc: _fallback_draft(
            student_input,
            analysis,
            research,
            decomposition,
            evaluated_research,
            exc,
        ),
        student_input,
        analysis,
        research,
        decomposition,
        evaluated_research,
        knowledge_context,
        learner_context,
        adaptive_instructions,
    )
    validation = _run_step(
        "validation",
        validate_study_plan,
        _fallback_validation,
        student_input,
        draft_plan,
        evaluated_research,
    )
    review = _run_step(
        "review",
        reviewer_agent,
        lambda exc: _fallback_review(draft_plan, exc),
        draft_plan,
        validation,
    )

    print(
        f"[study_plan] 完成学习计划，总耗时 {time.time() - workflow_start:.1f}s "
        f"（review 是否走降级: {review.review_summary.startswith('已直接返回初版计划')}）",
        flush=True,
    )
    return {
        "analysis": analysis,
        "decomposition": decomposition,
        "knowledge_map": knowledge_map,
        "research": research,
        "evaluated_research": evaluated_research,
        "draft_plan": draft_plan,
        "validation": validation,
        "review": review,
        "final_plan": review.final_plan_markdown,
    }


def _plan_context_to_text(plan_context: Dict[str, object]) -> str:
    """PlanContext → 注入 Planner 的画像上下文文本。"""
    lines = ["学习者状态（来自本地 Learner Model）："]
    known = plan_context.get("known_topics") or []
    unknown = plan_context.get("unknown_topics") or []
    review = plan_context.get("topics_needing_review") or []
    background_facts = plan_context.get("background_facts") or []
    if background_facts:
        lines.append(f"- 背景：{'；'.join(background_facts[:6])}")
    if known:
        lines.append(f"- 已了解/可跳过基础：{'、'.join(known[:6])}")
    if unknown:
        lines.append(f"- 新内容（按顺序学）：{'、'.join(unknown[:6])}")
    if review:
        lines.append(f"- 需要复习：{'、'.join(review[:6])}")
    if plan_context.get("preferred_style"):
        lines.append(f"- 偏好：{plan_context['preferred_style']}")
    if plan_context.get("semantic_memories"):
        lines.append(f"- 长期记忆：{'；'.join(plan_context['semantic_memories'][:2])}")
    return "\n".join(lines)


def _plan_context_instructions(plan_context: Dict[str, object]) -> str:
    """PlanContext → 教学指令（生成前就决定跳过/复习/重点）。"""
    parts = []
    if plan_context.get("known_topics"):
        parts.append("已知内容压缩学时，不安排入门讲解")
    if plan_context.get("topics_needing_review"):
        parts.append("为需复习的内容安排回顾环节")
    if plan_context.get("unknown_topics"):
        parts.append("新内容按前置关系安排顺序")
    note = plan_context.get("personalization_note")
    if note:
        parts.append(f"个性化说明：{note}")
    return "；".join(parts) if parts else "按学生当前状态安排学习顺序与重点。"
