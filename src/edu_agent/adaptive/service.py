"""AdaptiveService（范围收缩版）：领域课程解析。

只保留内置注册表（kc_graph.py 纯代码模板，只读共享）。
个性化 Plan Nodes 不再写共享 domain；resolve 不到返回 None。
"""

from __future__ import annotations

from typing import Optional

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_graph import get_course


def resolve_course_for(course_id: str) -> Optional[Course]:
    """获取领域课程：只查内置只读注册表（Java/Transformer 静态模板）。"""
    return get_course(course_id)
