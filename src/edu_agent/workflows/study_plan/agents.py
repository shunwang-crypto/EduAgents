import json
import logging
import re
import time
from typing import List

logger = logging.getLogger(__name__)

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
    LearningStageSuggestion,
    PlanValidationResult,
    ResearchResult,
    ReviewResult,
    StudentInput,
    WebResource,
)


def analyzer_agent(
    student_input: StudentInput,
    plan_context_text: str = "",
) -> AnalysisResult:
    """
    需求分析 Agent：
    使用 LangChain LLM + structured output 输出 AnalysisResult。
    plan_context_text：来自本地 Learner Model 的画像上下文（在需求分析阶段就影响
    level_summary / prerequisites），而非等到 Planner 才注入。
    """

    payload = student_input.model_dump()
    # Prompt always contains {plan_context}; pass an explicit empty value when
    # no learner-model context exists so ChatPromptTemplate can render it.
    payload["plan_context"] = plan_context_text or ""
    return invoke_structured_output(
        ANALYZER_PROMPT,
        AnalysisResult,
        payload,
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
        "准备可运行的学习环境",
    ]
    # 内部异常（reason）只记录日志，绝不得进入任何返回内容字段 —— 否则会被
    # build_knowledge_map 转换为面向用户的 Stage-3 Plan Step。
    if reason is not None:
        logger.warning("fallback decomposition used due to error: %r", reason)

    core = [
        f"{topic} 的核心术语、常见输入输出和适用场景",
        f"{topic} 的主流程和关键操作步骤",
        f"{topic} 学习目标中需要交付的作品或结果",
    ]
    applications = [
        f"围绕 {topic} 制作一份概念卡片和错误清单",
        f"完成一个能体现学习目标的 {topic} 小案例",
    ]
    # learning_sequence is retained for plan ordering only. Compatibility
    # normalization must not reinterpret it as prerequisite evidence.
    return DecompositionResult(
        core_concepts=core,
        prerequisite_concepts=prerequisites,
        learning_sequence=prerequisites + core + applications,
        difficulty_points=[
            "容易只阅读资料但缺少可提交产出",
            "容易把学习范围扩得过大，导致每日任务超时",
            "容易忽略检查标准，无法判断当天是否完成",
        ],
        stages=[
            LearningStageSuggestion(
                stage_id="stage-1",
                title="基础准备",
                objective=f"补齐 {topic} 前置知识并跑通环境",
                order=1,
            ),
            LearningStageSuggestion(
                stage_id="stage-2",
                title="核心学习",
                objective=f"围绕 {topic} 主流程完成最小应用案例",
                order=2,
            ),
            LearningStageSuggestion(
                stage_id="stage-3",
                title="综合应用",
                objective="完成最终作品、复盘薄弱点并整理验收记录",
                order=3,
            ),
        ],
        application_directions=applications + [
            "每天保留一条可检查产出，例如笔记、代码、截图或讲解录音",
        ],
    )


def decomposer_agent(
    student_input: StudentInput,
    analysis: AnalysisResult,
    plan_context_text: str = "",
    *,
    allow_fallback: bool = True,
) -> DecompositionResult:
    """
    内容拆解 Agent：
    使用 LLM 拆解前置知识、核心知识点、学习顺序、难点、阶段和实践方向。
    - stages 必须恰好 3 个（结构化 LearningStageSuggestion）。
    - plan_context_text：画像上下文在知识分解前生效（跳过/复习/顺序）。
    结构化解析失败时返回可展示、可继续规划的降级结果。
    """

    try:
        payload = {
            **student_input.model_dump(),
            "analysis": model_to_text(analysis),
            # DECOMPOSER_PROMPT requires this variable even for a first-time
            # learner with no stored context.
            "plan_context": plan_context_text or "",
        }
        result = invoke_structured_output(
            DECOMPOSER_PROMPT,
            DecompositionResult,
            payload,
            get_llm(temperature=0.2),
        )
        # 强制三阶段兜底：模型可能漏 stage 或多给
        if len(result.stages) != 3:
            result.stages = _normalize_stage_suggestions(result.stages)
        return result
    except Exception as exc:  # noqa: BLE001 - compatibility mode only
        if not allow_fallback:
            raise
        return _fallback_decomposition(student_input, analysis, exc)


def _normalize_stage_suggestions(stages: list) -> list:
    """把模型返回的阶段列表规整为恰好 3 个（缺的补默认）。"""
    from edu_agent.workflows.study_plan.schemas import LearningStageSuggestion

    defaults = [
        ("stage-1", "基础准备", "补齐必要背景、前置知识与环境"),
        ("stage-2", "核心学习", "掌握核心概念、方法与原理"),
        ("stage-3", "综合应用", "通过案例、小项目整合知识并总结"),
    ]
    ordered = sorted(stages or [], key=lambda s: getattr(s, "order", 0))
    result: list = []
    for order in range(1, 4):
        stage = next((s for s in ordered if getattr(s, "order", -1) == order), None)
        if stage is None or not (getattr(stage, "title", "") or "").strip():
            stage_id, title, objective = defaults[order - 1]
            stage = LearningStageSuggestion(stage_id=stage_id, title=title, objective=objective, order=order)
        result.append(stage)
    return result


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

    search_start = time.time()
    search_output = search_many(analysis.search_queries)
    print(
        f"[research] 搜索 {len(analysis.search_queries)} 个查询共耗时 {time.time() - search_start:.1f}s，"
        f"得到 {len(search_output['results'])} 条资源",
        flush=True,
    )
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
    llm_start = time.time()
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
    print(
        f"[research] LLM 总结完成，耗时 {time.time() - llm_start:.1f}s",
        flush=True,
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


def planner_agent(
    student_input: StudentInput,
    analysis: AnalysisResult,
    research: ResearchResult,
    decomposition: DecompositionResult | None = None,
    evaluated_research: EvaluatedResearchResult | None = None,
    knowledge_context: str = "无",
    learner_context: str = "",
    adaptive_instructions: str = "",
) -> DraftPlan:
    """
    学习规划 Agent：
    使用 LangChain LLM 生成 Markdown 学习计划。
    knowledge_context：来自已导入知识库的参考资料文本（命中块拼接），可为"无"。
    learner_context / adaptive_instructions：AdaptiveService 产出的画像上下文与教学指令。
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
            "knowledge_context": knowledge_context or "无",
            "learner_context": learner_context or "（暂无学习者上下文，按通用水平规划）",
            "adaptive_instructions": adaptive_instructions or "按学生当前状态安排学习顺序与重点。",
        }
    )
    return DraftPlan(plan_markdown=normalize_markdown_output(response))


def reviewer_agent(
    draft_plan: DraftPlan,
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
