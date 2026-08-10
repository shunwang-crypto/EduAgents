"""Prerequisite Policy：前置未掌握 → REVIEW_PREREQUISITE（用传递前置链）。

区分：
- KNOWN LOW prerequisite（mastery 明确低）→ PREREQUISITE_NOT_MASTERED / LOW_PREREQUISITE_MASTERY
- UNKNOWN prerequisite（mastery=None，无证据）→ PREREQUISITE_UNKNOWN（不默认通过，也不武断「不会」）
"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import (
    REASON_LOW_PREREQUISITE_MASTERY,
    REASON_PREREQUISITE_UNKNOWN,
)
from edu_agent.adaptive.policies.mastery import MASTERED_THRESHOLD
from edu_agent.domain.learning.kc_graph import Course
from edu_agent.learner_model.schemas import KnowledgeItem


def prerequisite_policy(
    target_kc: str,
    course: Course,
    knowledge_map: Dict[str, KnowledgeItem],
    reason_codes: List[str],
) -> Dict[str, object]:
    """目标 KC 的前置链中未满足的部分 → REVIEW_PREREQUISITE。"""
    missing: List[str] = []
    unknown: List[str] = []
    for prereq in course.all_prerequisites_transitive(target_kc):
        item = knowledge_map.get(prereq)
        if item is None or item.mastery is None:
            unknown.append(prereq)  # UNKNOWN：不自动通过，但也不武断「不会」
            continue
        if item.mastery < MASTERED_THRESHOLD:
            missing.append(prereq)  # KNOWN LOW：确认未掌握

    actions: List[str] = []
    content_order: List[str] = []
    if missing:
        reason_codes.append(REASON_LOW_PREREQUISITE_MASTERY)
        actions.append("REVIEW_PREREQUISITE")
        content_order += missing
    if unknown:
        reason_codes.append(REASON_PREREQUISITE_UNKNOWN)
        actions.append("CHECK_UNDERSTANDING")
        content_order += unknown

    if missing or unknown:
        actions = list(dict.fromkeys(actions + ["EXPLAIN", "WORKED_EXAMPLE"]))
        content_order = list(dict.fromkeys(content_order + [target_kc]))
        return {
            "review_prerequisite": bool(missing),
            "prerequisite_topics": list(dict.fromkeys(missing + unknown)),
            "pedagogical_actions": actions,
            "content_order": content_order,
        }
    return {}
