"""LearningContextService：统一解析 user/course → LearningContext + Bundle + Course。

业务层禁止直接读固定 user/course 配置；user_id 由调用方（Router）传入。
"""

from __future__ import annotations

from typing import Optional, Tuple

from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.schemas import LearnerStateBundle, LearningContext
from edu_agent.learner_model.service import LearnerModelService


def resolve_context(
    user_id: str,
    course_id: Optional[str] = None,
    learner: Optional[LearnerModelService] = None,
) -> LearningContext:
    """构造统一 LearningContext（course_id 可为 None = 普通对话）。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    if course_id:
        learner.ensure_course(user_id, course_id)
    return LearningContext(user_id=user_id, course_id=course_id or "")


def resolve_bundle_and_course(
    user_id: str,
    course_id: Optional[str] = None,
    learner: Optional[LearnerModelService] = None,
) -> Tuple[LearnerStateBundle, Optional[Course]]:
    """一次取齐 bundle + 领域 Course（内置注册表 → SQLite 持久化）。"""
    from edu_agent.adaptive.service import resolve_course_for

    learner = learner or LearnerModelService()
    ctx = resolve_context(user_id, course_id, learner)
    bundle = learner.build_bundle(user_id, ctx.course_id or "")
    course = resolve_course_for(ctx.course_id) if ctx.course_id else None
    return bundle, course
