import json
import re
from typing import List

from edu_agent.core.agent_runner import (
    invoke_structured_output,
    model_to_text,
    normalize_markdown_output,
)
from edu_agent.core.llm import get_llm
from edu_agent.tools.web_search import search_many
from edu_agent.workflows.study_plan.prompts import (
    ANALYZER_PROMPT,
    DECOMPOSER_PROMPT,
    PLANNER_PROMPT,
    PRACTICE_DESIGNER_PROMPT,
    RESOURCE_EVALUATOR_PROMPT,
    RESEARCHER_PROMPT,
    REVIEWER_PROMPT,
)
from edu_agent.workflows.study_plan.resource_rules import evaluate_resources_locally
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
    WebResource,
)


def analyzer_agent(student_input: StudentInput) -> AnalysisResult:
    """
    需求分析 Agent：
    使用 LangChain LLM + structured output 输出 AnalysisResult。
    """

    return invoke_structured_output(
        ANALYZER_PROMPT,
        AnalysisResult,
        student_input.model_dump(),
        get_llm(temperature=0.2),
    )


def _fallback_decomposition(
    student_input: StudentInput,
    analysis: AnalysisResult,
    reason: Exception | None = None,
) -> DecompositionResult:
    topic = analysis.topic or student_input.topic
    prerequisites = analysis.prerequisites or [
        f"{topic} 相关术语和基本概念",
        "准备可执行的练习环境和记录模板",
    ]
    suffix = f"（降级生成：{reason}）" if reason else ""

    return DecompositionResult(
        core_concepts=[
            f"{topic} 的核心术语、常见输入输出和适用场景",
            f"{topic} 的主流程和关键操作步骤",
            f"{topic} 学习目标中需要交付的作品或结果",
        ],
        prerequisite_concepts=prerequisites,
        learning_sequence=[
            "先补齐前置知识并确认学习环境可用",
            f"再学习 {topic} 的核心概念和最小可运行示例",
            "随后按阶段完成练习、复盘问题并迭代产出",
            f"最后完成一个贴近目标的 {topic} 综合任务",
        ],
        difficulty_points=[
            "容易只阅读资料但缺少可提交产出",
            "容易把学习范围扩得过大，导致每日任务超时",
            "容易忽略检查标准，无法判断当天是否完成",
        ],
        stage_suggestions=[
            f"基础准备阶段：补齐 {topic} 前置知识并跑通环境",
            f"核心学习阶段：围绕 {topic} 主流程完成小练习",
            "综合产出阶段：完成最终作品、复盘薄弱点并整理验收记录",
        ],
        practice_directions=[
            f"围绕 {topic} 制作一份概念卡片和错误清单",
            f"完成一个能体现学习目标的 {topic} 小案例",
            "每天保留一条可检查产出，例如笔记、代码、截图或讲解录音",
            suffix,
        ]
        if suffix
        else [
            f"围绕 {topic} 制作一份概念卡片和错误清单",
            f"完成一个能体现学习目标的 {topic} 小案例",
            "每天保留一条可检查产出，例如笔记、代码、截图或讲解录音",
        ],
    )


def decomposer_agent(
    student_input: StudentInput,
    analysis: AnalysisResult,
) -> DecompositionResult:
    """
    内容拆解 Agent：
    使用 LLM 拆解前置知识、核心知识点、学习顺序、难点、阶段和实践方向。
    结构化解析失败时返回可展示、可继续规划的降级结果。
    """

    try:
        return invoke_structured_output(
            DECOMPOSER_PROMPT,
            DecompositionResult,
            {
                **student_input.model_dump(),
                "analysis": model_to_text(analysis),
            },
            get_llm(temperature=0.2),
        )
    except Exception as exc:  # noqa: BLE001 - agent should keep workflow usable
        return _fallback_decomposition(student_input, analysis, exc)


def researcher_agent(analysis: AnalysisResult) -> ResearchResult:
    """
    资料搜索 Agent：
    根据 analysis.search_queries 调用 web_search 工具。
    再使用 LLM 总结搜索结果，输出 ResearchResult。
    如果未启用搜索，返回 search_enabled=False。
    """

    if not analysis.need_web_search:
        return ResearchResult(
            search_enabled=False,
            summary="需求分析认为第一版可以不依赖联网搜索，已基于学生输入继续规划。",
            key_points=[],
            resources=[],
        )

    search_output = search_many(analysis.search_queries)
    resources: List[WebResource] = search_output["results"]

    if not search_output["enabled"]:
        return ResearchResult(
            search_enabled=False,
            summary=search_output["message"],
            key_points=[],
            resources=[],
        )

    search_results_text = json.dumps(
        [resource.model_dump() for resource in resources],
        ensure_ascii=False,
        indent=2,
    )
    result = invoke_structured_output(
        RESEARCHER_PROMPT,
        ResearchResult,
        {
            "topic": analysis.topic,
            "analysis": model_to_text(analysis),
            "search_results": search_results_text,
        },
        get_llm(temperature=0.2),
    )

    # Keep the real tool status even if the model omits or rewrites it.
    result.search_enabled = True
    if not result.resources and resources:
        result.resources = resources
    return result


def _merge_with_known_resources(
    evaluated_resources: List[EvaluatedResource],
    research: ResearchResult,
    fallback_resources: List[EvaluatedResource],
) -> List[EvaluatedResource]:
    by_url = {resource.url: resource for resource in research.resources if resource.url}
    by_title = {resource.title.strip().lower(): resource for resource in research.resources}
    filtered: List[EvaluatedResource] = []

    for evaluated in evaluated_resources:
        original = None
        if evaluated.url:
            original = by_url.get(evaluated.url)
        if original is None:
            original = by_title.get(evaluated.title.strip().lower())
        if original is None:
            continue

        evaluated.url = original.url
        evaluated.title = original.title
        if not evaluated.summary:
            evaluated.summary = original.summary
        filtered.append(evaluated)

    return filtered or fallback_resources


def resource_evaluator_agent(
    research: ResearchResult,
    decomposition: DecompositionResult,
) -> EvaluatedResearchResult:
    """
    资源评估 Agent：
    对 Researcher 的搜索结果做质量筛选，并保留纯规则降级逻辑。
    """

    if not research.search_enabled:
        return EvaluatedResearchResult(
            search_enabled=False,
            summary=research.summary or "未启用联网搜索，未生成外部资源链接。",
            key_points=research.key_points,
            resources=[],
        )

    fallback_resources = evaluate_resources_locally(research, decomposition)
    if not research.resources:
        return EvaluatedResearchResult(
            search_enabled=True,
            summary=research.summary or "联网搜索已启用，但没有获得可评估的资源。",
            key_points=research.key_points,
            resources=[],
        )

    try:
        result = invoke_structured_output(
            RESOURCE_EVALUATOR_PROMPT,
            EvaluatedResearchResult,
            {
                "research": model_to_text(research),
                "decomposition": model_to_text(decomposition),
            },
            get_llm(temperature=0.15),
        )
        result.search_enabled = True
        result.key_points = result.key_points or research.key_points
        result.resources = _merge_with_known_resources(
            result.resources,
            research,
            fallback_resources,
        )
        if not result.summary:
            result.summary = "已根据资源相关性、来源类型和可实践性完成筛选。"
        return result
    except Exception as exc:  # noqa: BLE001 - local rules are an intentional fallback
        return EvaluatedResearchResult(
            search_enabled=True,
            summary=f"资源质量评估 Agent 暂时不可用，已使用本地规则筛选。原因：{exc}",
            key_points=research.key_points,
            resources=fallback_resources,
        )


def _infer_day_count(markdown: str) -> int:
    day_numbers = {
        int(match)
        for match in re.findall(r"(?:第\s*)?(\d{1,3})\s*天", markdown)
    }
    return max(day_numbers) if day_numbers else 0


def _fallback_practice_plan(
    draft_plan: DraftPlan,
    decomposition: DecompositionResult,
    reason: Exception | None = None,
) -> PracticePlan:
    sequence = decomposition.learning_sequence or decomposition.core_concepts or ["学习主题"]
    day_count = _infer_day_count(draft_plan.plan_markdown) or min(max(len(sequence), 3), 7)
    daily_tasks = []
    for day in range(1, day_count + 1):
        concept = sequence[(day - 1) % len(sequence)]
        daily_tasks.append(
            f"第 {day} 天：围绕「{concept}」完成一个可提交练习，并记录 1 个卡点和 1 条改进动作。"
        )

    stage_tasks = []
    stages = decomposition.stage_suggestions or ["基础阶段", "实践阶段", "综合阶段"]
    for index, stage in enumerate(stages, start=1):
        direction = decomposition.practice_directions[
            (index - 1) % len(decomposition.practice_directions)
        ] if decomposition.practice_directions else "提交一份阶段产出"
        stage_tasks.append(
            f"{stage}：完成「{direction}」，并用 3 条证据说明阶段目标已达成。"
        )

    suffix = f" 降级原因：{reason}" if reason else ""
    return PracticePlan(
        practice_summary=f"练习任务围绕知识点拆解生成，覆盖每日产出、阶段检查和最终综合任务。{suffix}".strip(),
        daily_practice_tasks=daily_tasks,
        stage_check_tasks=stage_tasks,
        final_project="完成一个能够展示学习目标的综合作品，并附上操作步骤、关键截图或结果说明、复盘清单。",
        reflection_questions=[
            "今天的产出能否被别人复现或检查？还缺哪一步证据？",
            "哪个概念最影响后续学习？明天要用什么小任务验证它？",
            "本阶段产出是否直接服务最终目标？需要删减哪些旁支内容？",
        ],
    )


def practice_designer_agent(
    draft_plan: DraftPlan,
    decomposition: DecompositionResult,
) -> PracticePlan:
    """
    练习设计 Agent：
    根据初版计划和内容拆解生成每日练习、阶段检查、最终项目和反思问题。
    """

    try:
        return invoke_structured_output(
            PRACTICE_DESIGNER_PROMPT,
            PracticePlan,
            {
                "draft_plan": draft_plan.plan_markdown,
                "decomposition": model_to_text(decomposition),
            },
            get_llm(temperature=0.25),
        )
    except Exception as exc:  # noqa: BLE001 - agent should return usable tasks
        return _fallback_practice_plan(draft_plan, decomposition, exc)


def planner_agent(
    student_input: StudentInput,
    analysis: AnalysisResult,
    research: ResearchResult,
    decomposition: DecompositionResult | None = None,
    evaluated_research: EvaluatedResearchResult | None = None,
) -> DraftPlan:
    """
    学习规划 Agent：
    使用 LangChain LLM 生成 Markdown 学习计划。
    """

    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_template(PLANNER_PROMPT)
    chain = prompt | get_llm(temperature=0.35)
    decomposition = decomposition or _fallback_decomposition(student_input, analysis)
    evaluated_research = evaluated_research or EvaluatedResearchResult(
        search_enabled=research.search_enabled,
        summary=research.summary,
        key_points=research.key_points,
        resources=[],
    )
    response = chain.invoke(
        {
            **student_input.model_dump(),
            "analysis": model_to_text(analysis),
            "decomposition": model_to_text(decomposition),
            "research": model_to_text(research),
            "evaluated_research": model_to_text(evaluated_research),
        }
    )
    return DraftPlan(plan_markdown=normalize_markdown_output(response))


def reviewer_agent(
    draft_plan: DraftPlan,
    practice_plan: PracticePlan | None = None,
    validation_result: PlanValidationResult | None = None,
) -> ReviewResult:
    """
    计划评估 Agent：
    使用 LangChain LLM 检查并优化初版学习计划。
    """

    result = invoke_structured_output(
        REVIEWER_PROMPT,
        ReviewResult,
        {
            "draft_plan": draft_plan.plan_markdown,
            "practice_plan": model_to_text(practice_plan) if practice_plan else "未生成练习设计结果。",
            "validation_result": (
                model_to_text(validation_result)
                if validation_result
                else "未生成规则校验结果。"
            ),
        },
        get_llm(temperature=0.2),
    )
    result.final_plan_markdown = normalize_markdown_output(result.final_plan_markdown)
    return result
