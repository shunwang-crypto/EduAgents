"""AdaptiveContextSelector：按任务类型只挑选相关的 LearnerState 子集。

禁止把完整 LearnerState 塞给 LLM。不同任务类型返回不同上下文：
- study_plan：Goal + 目标 KC + KC Graph + 掌握度快照 + 能力 + 偏好 + 进度
- topic_tutor：目标 KC + 前置 + 误解 + 理解能力 + 偏好 + 会话状态
- adaptive_qa：映射到的 KC + 前置 + 误解 + 能力 + 偏好
- plan_chat：当前计划 + 进度 + 弱 KC + 节奏 + 可用时间
"""

from __future__ import annotations

from typing import Optional

from edu_agent.adaptive.schemas import SelectedLearnerContext, TaskType
from edu_agent.domain.learning.kc_graph import Course
from edu_agent.integrations.learner_state.schemas import LearnerStateBundle


def _freshness_of(bundle: LearnerStateBundle) -> str:
    return bundle.course_state.freshness


def _state_version_of(bundle: LearnerStateBundle) -> Optional[int]:
    return bundle.course_state.state_version


def select_context(
    bundle: LearnerStateBundle,
    task_type: TaskType,
    course: Optional[Course] = None,
    target_kc: Optional[str] = None,
    query: str = "",
) -> SelectedLearnerContext:
    """按任务类型从 LearnerStateBundle 中选出最小相关上下文。"""
    course_state = bundle.course_state
    global_state = bundle.global_state
    goal = bundle.active_goal

    base = SelectedLearnerContext(
        task_type=task_type,
        user_id=bundle.user_id,
        course_id=bundle.course_id,
        goal_id=goal.goal_id if goal else course_state.goal_id,
        goal_name=goal.goal_name if goal else "",
        goal_target=goal.target if goal else "",
        goal_progress=goal.progress if goal else course_state.progress,
        freshness=_freshness_of(bundle),
        learner_state_version=_state_version_of(bundle),
        abilities={k: v.score for k, v in course_state.abilities.items()},
        preferences={
            "preferred_mode": global_state.preferences.preferred_mode,
            "pace_factor": global_state.preferences.pace_factor,
            "scaffold_preference": global_state.preferences.scaffold_preference,
            "mode_effectiveness": {
                k: v.model_dump() for k, v in global_state.preferences.mode_effectiveness.items()
            },
        },
        behavior=course_state.behavior.model_dump(),
    )

    if task_type == "study_plan":
        return _select_study_plan(base, bundle, course)
    if task_type == "adaptive_qa":
        return _select_qa(base, bundle, course, target_kc, query)
    return _select_topic_tutor(base, bundle, course, target_kc)


def _select_study_plan(
    base: SelectedLearnerContext,
    bundle: LearnerStateBundle,
    course: Optional[Course],
) -> SelectedLearnerContext:
    """学习计划：全课程掌握度快照 + 目标 KC + 能力 + 偏好。"""
    course_state = bundle.course_state
    goal_kcs = bundle.active_goal.target_kcs if bundle.active_goal else []
    base.knowledge_snapshot = [
        item.model_dump() for item in course_state.knowledge
    ]
    # 目标 KC 优先展示
    if goal_kcs:
        target_items = [
            item.model_dump() for item in course_state.knowledge
            if item.kc_id in goal_kcs
        ]
        if target_items:
            base.knowledge_snapshot = target_items + [
                item.model_dump() for item in course_state.knowledge
                if item.kc_id not in goal_kcs
            ]
    base.target_kc = goal_kcs[0] if goal_kcs else None
    base.target_kc_name = base.target_kc
    base.misconceptions = [m.model_dump() for m in course_state.misconceptions]
    if course:
        base.prerequisites = course.prerequisites(base.target_kc) if base.target_kc else []
    return base


def _select_topic_tutor(
    base: SelectedLearnerContext,
    bundle: LearnerStateBundle,
    course: Optional[Course],
    target_kc: Optional[str],
) -> SelectedLearnerContext:
    """专题讲解：目标 KC + 前置 + 误解 + 理解能力，不加载无关课程 mastery。"""
    course_state = bundle.course_state
    kc = course.kc_by_id(target_kc) if course and target_kc else None
    base.target_kc = target_kc or (kc.kc_id if kc else None)
    base.target_kc_name = kc.title if kc else (target_kc or "")

    if course and target_kc:
        prereqs = course.all_prerequisites_transitive(target_kc)
        base.prerequisites = course.prerequisites(target_kc)
        base.knowledge_snapshot = [
            item.model_dump() for item in course_state.knowledge
            if item.kc_id == target_kc or item.kc_id in prereqs
        ]
        base.prerequisite_knowledge = [
            item.model_dump() for item in course_state.knowledge if item.kc_id in prereqs
        ]
    else:
        base.knowledge_snapshot = [
            item.model_dump() for item in course_state.knowledge[:8]
        ]

    base.misconceptions = [
        m.model_dump() for m in course_state.misconceptions
        if not target_kc or m.kc_id == target_kc or m.kc_id in (base.prerequisites or [])
    ]
    # 能力：讲解主要受 understanding/application/expression 影响
    for ability in ("understanding", "application", "expression"):
        if ability in base.abilities:
            continue
    return base


def _select_qa(
    base: SelectedLearnerContext,
    bundle: LearnerStateBundle,
    course: Optional[Course],
    target_kc: Optional[str],
    query: str,
) -> SelectedLearnerContext:
    """问答：先映射目标 KC，再加载相关上下文；非学习型问题返回最小上下文。"""
    # 学习型问题启发式：出现概念性问句才映射 KC
    if target_kc:
        return _select_topic_tutor(base, bundle, course, target_kc)
    # 非学习型问题（如"怎么查日志"）：只带偏好与基础画像
    base.knowledge_snapshot = []
    base.misconceptions = []
    return base
