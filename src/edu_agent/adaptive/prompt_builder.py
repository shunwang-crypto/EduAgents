"""PromptBuilder：把 AdaptiveDecision + SelectedContext + 领域内容转成 LLM 上下文。

自适应逻辑在 Policy 完成；这里只做「结构化结果 → Prompt 片段」的转换。
"""

from __future__ import annotations

from typing import Optional

from edu_agent.adaptive.schemas import AdaptiveDecision, SelectedLearnerContext


def build_prompt_context(
    adaptive_decision: AdaptiveDecision,
    selected_context: SelectedLearnerContext,
    domain_context: str = "",
    retrieved_knowledge: str = "",
    semantic_memory: str = "",
    user_request: str = "",
    system_role: str = "",
) -> dict:
    """生成结构化的 LLM 上下文（key-value，供各 workflow prompt 使用）。

    返回的 dict 至少包含：
    - system_role
    - task
    - current_goal
    - adaptive_decision（JSON 文本）
    - learner_context（SelectedLearnerContext.to_prompt_snippet）
    - domain_context
    - retrieved_knowledge
    - semantic_memory
    - user_request
    """
    return {
        "system_role": system_role or "你是一名自适应学习系统的教学助手。",
        "task": _task_label(adaptive_decision.task_type),
        "current_goal": _goal_label(selected_context),
        "adaptive_decision": adaptive_decision.model_dump_json(indent=2),
        "learner_context": selected_context.to_prompt_snippet(),
        "domain_context": domain_context,
        "retrieved_knowledge": retrieved_knowledge,
        "semantic_memory": semantic_memory,
        "user_request": user_request,
    }


def _task_label(task_type: str) -> str:
    return {
        "study_plan": "根据学习者状态生成自适应学习计划",
        "topic_tutor": "针对目标知识点的个性化讲解",
        "adaptive_qa": "结合学习者状态的知识问答",
        "plan_chat": "基于学习计划的自适应调整问答",
    }.get(task_type, "教学任务")


def _goal_label(context: SelectedLearnerContext) -> str:
    if context.goal_name:
        return (
            f"{context.goal_name}（进度 {context.goal_progress:.0%}）"
            + (f"：{context.goal_target}" if context.goal_target else "")
        )
    return f"课程 {context.course_id or '未指定'}"


def decision_instructions(decision: AdaptiveDecision) -> str:
    """把教学动作转成给 LLM 的指令片段（人话）。"""
    mapping = {
        "EXPLAIN": "先解释核心概念，讲清楚「是什么、为什么」。",
        "WORKED_EXAMPLE": "给出完整可运行的示例，并逐步讲解每个关键步骤。",
        "PARTIAL_EXAMPLE": "给出示例的骨架，让学习者补全关键部分。",
        "HINT": "先给提示，引导学习者自己思考。",
        "ANALOGY": "用学习者熟悉的类比帮助建立直觉。",
        "COUNTEREXAMPLE": "给出反例，澄清容易混淆的情况。",
        "REVIEW_PREREQUISITE": f"先复习前置知识：{('、'.join(decision.prerequisite_topics)) or '相关前置'}。",
        "SUMMARIZE": "用简洁的方式总结要点，建立知识联系。",
        "CONCEPT_COMPARISON": "对比容易混淆的概念，讲清区别与联系。",
        "DECOMPOSE": "把复杂内容拆成小步骤，逐步展开。",
        "SIMPLIFY": "降低抽象程度，用更直白的方式表达。",
        "DEEPEN": "深入原理与实现细节，补充进阶内容。",
        "CHECK_UNDERSTANDING": "讲解后提出一个理解检查问题，让学习者自己解释。",
        "SOCRATIC_QUESTION": "用苏格拉底式提问引导学习者推导出结论。",
    }
    seen: list[str] = []
    for action in decision.pedagogical_actions:
        if action in mapping and action not in seen:
            seen.append(action)
    return "\n".join(f"- {mapping[a]}" for a in seen) or "- 直接讲解。"
