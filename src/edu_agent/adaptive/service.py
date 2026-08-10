"""AdaptiveService：一键完成「读 LearnerState → 选上下文 → 决策 → Prompt 上下文」。

工作流与前端只需要调用 prepare_adaptive_context(...)，
无需关心 Provider / ContextSelector / Policy 的组装细节。
"""

from __future__ import annotations

from typing import Optional

from edu_agent.adaptive.context_selector import select_context
from edu_agent.adaptive.policy import make_decision
from edu_agent.adaptive.prompt_builder import build_prompt_context, decision_instructions
from edu_agent.adaptive.schemas import AdaptiveDecision, SelectedLearnerContext, TaskType
from edu_agent.domain.kc_graph import Course, get_course
from edu_agent.integrations.learner_state.provider import get_learner_state_provider
from edu_agent.integrations.learner_state.schemas import LearnerStateBundle


def load_bundle(
    user_id: str = "",
    course_id: str = "",
    provider_name: str = "",
) -> LearnerStateBundle:
    """读取 LearnerStateBundle（user_id/course_id 缺省用配置默认值）。"""
    from edu_agent.config.settings import get_settings

    settings = get_settings()
    user_id = user_id or settings.learner_state_user_id
    course_id = course_id or settings.learner_state_course_id
    provider = get_learner_state_provider(provider_name)
    return provider.get_bundle(user_id=user_id, course_id=course_id)


def prepare_adaptive_context(
    task_type: TaskType,
    target_kc: Optional[str] = None,
    query: str = "",
    user_id: str = "",
    course_id: str = "",
    session_re_explain_count: int = 0,
    delivery_mode_hint: str = "",
    bundle: Optional[LearnerStateBundle] = None,
) -> tuple[SelectedLearnerContext, AdaptiveDecision, dict]:
    """核心入口：返回 (selected_context, adaptive_decision, prompt_context)。

    - 课程未注册时退化为通用决策（不崩）。
    - task_type 决定上下文选择范围（多课程隔离由 course_id 保证）。
    """
    if bundle is None:
        bundle = load_bundle(user_id=user_id, course_id=course_id)

    course: Optional[Course] = get_course(bundle.course_id)

    context = select_context(
        bundle=bundle,
        task_type=task_type,
        course=course,
        target_kc=target_kc,
        query=query,
    )

    if course is None:
        course = Course(course_id=bundle.course_id, title=bundle.course_id)

    decision = make_decision(
        context=context,
        course=course,
        task_type=task_type,
        session_re_explain_count=session_re_explain_count,
        delivery_mode_hint=delivery_mode_hint,
    )

    instructions = decision_instructions(decision)
    prompt_context = build_prompt_context(
        adaptive_decision=decision,
        selected_context=context,
        user_request=query,
        system_role=(
            "你是一名自适应学习系统的教学助手。必须遵守 AdaptiveDecision 的教学动作，"
            "不得生成练习题、测验或考试内容。"
        ),
    )
    prompt_context["adaptive_instructions"] = instructions
    return context, decision, prompt_context


def decision_summary(decision: AdaptiveDecision) -> dict:
    """决策的展示快照（供前端 Adaptive Decision Trace）。"""
    return {
        "target_kc": decision.target_kc,
        "next_kc": decision.next_kc,
        "depth": decision.depth,
        "difficulty": decision.difficulty,
        "review_prerequisite": decision.review_prerequisite,
        "prerequisite_topics": decision.prerequisite_topics,
        "pedagogical_actions": decision.pedagogical_actions,
        "scaffold_level": decision.scaffold_level,
        "delivery_mode": decision.delivery_mode,
        "example_count": decision.example_count,
        "review_or_new": decision.review_or_new,
        "reason_codes": decision.reason_codes,
        "learner_state_version": decision.learner_state_version,
        "explain": decision.explain(),
    }
