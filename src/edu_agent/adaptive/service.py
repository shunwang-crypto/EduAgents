"""AdaptiveService（范围收缩版）：领域课程解析（内置注册表 → SQLite 持久化）。"""

from __future__ import annotations

from typing import Optional

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_graph import get_course
from edu_agent.learner_model.service import LearnerModelService


def resolve_course_for(course_id: str) -> Optional[Course]:
    """获取领域课程：先内置注册表，再本地持久化（自定义课程跨重启恢复）。"""
    course = get_course(course_id)
    if course is not None:
        return course
    try:
        from edu_agent.domain.learning.course_builder import load_course_from_repo

        service = LearnerModelService()
        return load_course_from_repo(service.repo, course_id)
    except Exception:  # noqa: BLE001 - 画像不可用时返回 None
        return None
