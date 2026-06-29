from typing import Any, Callable

from edu_agent.workflows.study_plan.agents import (
    analyzer_agent,
    decomposer_agent,
    planner_agent,
    practice_designer_agent,
    resource_evaluator_agent,
    researcher_agent,
    reviewer_agent,
)
from edu_agent.workflows.study_plan.schemas import (
    AnalysisResult,
    DecompositionResult,
    DraftPlan,
    EvaluatedResearchResult,
    EvaluatedResource,
    PlanValidationResult,
    PracticePlan,
    ResearchResult,
    ReviewResult,
    StudentInput,
)
from edu_agent.workflows.study_plan.validator import validate_study_plan


def _run_step(step_name: str, func: Callable[..., Any], fallback: Callable[[Exception], Any], *args):
    try:
        return func(*args)
    except Exception as exc:  # noqa: BLE001 - workflow should return displayable errors
        return fallback(exc)


def _fallback_analysis(student_input: StudentInput, exc: Exception) -> AnalysisResult:
    return AnalysisResult(
        topic=student_input.topic,
        level_summary=f"需求分析 Agent 暂时不可用，已保留学生原始基础描述：{student_input.level}",
        goal_summary=student_input.goal,
        prerequisites=["根据学习主题补充必要基础知识", "准备可运行的学习与练习环境"],
        need_web_search=False,
        search_queries=[],
    )


def _fallback_research(exc: Exception) -> ResearchResult:
    return ResearchResult(
        search_enabled=False,
        summary=f"资料搜索步骤未完成，原因：{exc}。将只基于学生输入生成学习规划。",
        key_points=[],
        resources=[],
    )


def _fallback_decomposition(
    student_input: StudentInput,
    analysis: AnalysisResult,
    exc: Exception,
) -> DecompositionResult:
    topic = analysis.topic or student_input.topic
    return DecompositionResult(
        core_concepts=[
            f"{topic} 的核心概念和术语",
            f"{topic} 的基本操作流程",
            f"{topic} 学习目标对应的交付产出",
        ],
        prerequisite_concepts=analysis.prerequisites
        or [f"{topic} 的前置知识", "可执行的练习环境"],
        learning_sequence=[
            "补齐前置知识并确认工具环境",
            f"学习 {topic} 的核心概念和最小示例",
            "完成阶段练习并复盘错误",
            "完成最终综合任务并整理验收记录",
        ],
        difficulty_points=[
            f"{topic} 范围可能过宽，需要聚焦当前周期主线",
            "每日任务需要有明确产出，否则难以检查进度",
        ],
        stage_suggestions=[
            "基础准备阶段：补齐前置知识和环境",
            "核心学习阶段：完成主题主线学习与小练习",
            "综合产出阶段：完成作品、验收和复盘",
        ],
        practice_directions=[
            f"完成一个和 {topic} 直接相关的小案例",
            "每天保留笔记、代码、截图或讲解记录作为检查证据",
            f"内容拆解步骤使用降级结果，原因：{exc}",
        ],
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
        summary=f"资源质量评估步骤未完成，原因：{exc}。已使用 Researcher 原始结果降级。",
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
            f"完成一个与「{concept}」相关的小练习 | 提交笔记、练习结果和疑问记录 | {student_input.daily_time} |"
        )

    stage_rows = []
    stage_suggestions = decomposition.stage_suggestions or ["基础准备", "核心学习", "综合产出"]
    for index, stage in enumerate(stage_suggestions[:5], start=1):
        start_day = max(1, round((index - 1) * student_input.days / len(stage_suggestions)) + 1)
        end_day = max(start_day, round(index * student_input.days / len(stage_suggestions)))
        stage_rows.append(
            f"| 阶段 {index} | 第 {start_day}-{end_day} 天 | {stage} | "
            "提交阶段练习、问题清单和复盘记录 |"
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
            "| 实践项目 | 选择一个小型案例或题目 | 用于最终综合产出 | 实践阶段 |",
        ]

    markdown = f"""# {topic} 学习规划

> 初版计划由降级模板生成，原因：{exc}

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
- 围绕核心知识点安排每日学习和小练习，避免把旁支内容挤进主线。
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

## 六、练习与检查任务

| 阶段/天数 | 练习任务 | 检查标准 |
| -- | -- | -- |
| 每日 | 根据当天学习主题完成一个小练习 | 能提交练习结果并说明一个关键判断 |
| 阶段 | 汇总阶段问题清单并修正至少 2 个卡点 | 复盘记录中包含问题、修正动作和结果 |
| 最终 | 完成一个贴近目标的综合任务 | 有完整产出、关键步骤说明和自检清单 |

## 七、推荐资源

| 类型 | 资源 | 用途 | 适合阶段 |
| -- | -- | -- | -- |
{chr(10).join(resource_rows)}

## 八、最终验收标准

- 能独立说明 {topic} 的核心概念、使用场景和常见限制。
- 能提交覆盖每日任务的笔记、练习结果和问题清单。
- 能完成一个和学习目标直接相关的综合作品或案例。
- 能用自检清单指出 2 个薄弱点和下一步修正动作。

## 九、执行建议

- 每天结束前用 5 分钟记录“完成产出、卡点、明日动作”。
- 遇到卡点时先缩小问题范围，保留错误信息或过程截图，再查资料。
- 如果当天任务超过 {student_input.daily_time}，优先保留主线任务，把拓展内容移到复盘后处理。
"""
    return DraftPlan(plan_markdown=markdown)


def _fallback_practice(
    draft_plan: DraftPlan,
    decomposition: DecompositionResult,
    exc: Exception,
) -> PracticePlan:
    concepts = decomposition.learning_sequence or decomposition.core_concepts or ["当天主题"]
    daily_tasks = [
        f"第 {index} 天：围绕「{concept}」完成一个可提交练习，并记录检查结果。"
        for index, concept in enumerate(concepts[:7], start=1)
    ]
    if not daily_tasks:
        daily_tasks = ["第 1 天：完成一个与学习主题直接相关的小练习，并记录检查结果。"]

    return PracticePlan(
        practice_summary=f"练习设计步骤未完成，原因：{exc}。已生成可继续 Review 的降级练习任务。",
        daily_practice_tasks=daily_tasks,
        stage_check_tasks=[
            f"{stage}：提交阶段产出、问题清单和下一步修正动作。"
            for stage in (decomposition.stage_suggestions or ["基础阶段", "实践阶段", "综合阶段"])
        ],
        final_project="完成一个贴近学习目标的综合作品，并附上过程说明、结果截图或输出、复盘清单。",
        reflection_questions=[
            "今天是否留下了可检查产出？",
            "哪个卡点阻塞了后续学习？下一步如何验证？",
            "阶段产出是否仍然对齐最终目标？",
        ],
    )


def _fallback_validation(exc: Exception) -> PlanValidationResult:
    return PlanValidationResult(
        passed=False,
        issues=[f"规则校验步骤未完成，原因：{exc}。"],
        suggestions=["请人工检查计划章节、每日天数、任务量、练习任务和资源链接。"],
        checked_rules=[],
    )


def _fallback_review(draft_plan: DraftPlan, exc: Exception) -> ReviewResult:
    return ReviewResult(
        review_summary=f"Reviewer Agent 暂时不可用，已直接返回初版计划。原因：{exc}",
        problems_found=["未完成 LLM 自动审查，请人工确认任务量和资源推荐是否合适。"],
        final_plan_markdown=draft_plan.plan_markdown,
    )


def run_study_plan_workflow(student_input: StudentInput) -> dict:
    analysis = _run_step(
        "analysis",
        analyzer_agent,
        lambda exc: _fallback_analysis(student_input, exc),
        student_input,
    )
    decomposition = _run_step(
        "decomposition",
        decomposer_agent,
        lambda exc: _fallback_decomposition(student_input, analysis, exc),
        student_input,
        analysis,
    )
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
    )
    practice_plan = _run_step(
        "practice_plan",
        practice_designer_agent,
        lambda exc: _fallback_practice(draft_plan, decomposition, exc),
        draft_plan,
        decomposition,
    )
    validation = _run_step(
        "validation",
        validate_study_plan,
        _fallback_validation,
        student_input,
        draft_plan,
        practice_plan,
        evaluated_research,
    )
    review = _run_step(
        "review",
        reviewer_agent,
        lambda exc: _fallback_review(draft_plan, exc),
        draft_plan,
        practice_plan,
        validation,
    )

    return {
        "analysis": analysis,
        "decomposition": decomposition,
        "research": research,
        "evaluated_research": evaluated_research,
        "draft_plan": draft_plan,
        "practice_plan": practice_plan,
        "validation": validation,
        "review": review,
        "final_plan": review.final_plan_markdown,
    }
