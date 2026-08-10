"""Prerequisite Policy：前置未掌握 → REVIEW_PREREQUISITE（用传递前置链）。"""

from __future__ import annotations

from typing import Dict, List

from edu_agent.adaptive.reason_codes import REASON_LOW_PREREQUISITE_MASTERY
from edu_agent.adaptive.policies.mastery import MASTERED_THRESHOLD
from edu_agent.domain.learning.kc_graph import Course
from edu_agent.learner_model.schemas import KnowledgeItem


def prerequisite_policy(
    target_kc: str,
    course: Course,
    knowledge_map: Dict[str, KnowledgeItem],
    reason_codes: List[str],
) -> Dict[str, object]:
    """目标 KC 的前置链（如 多态→继承→封装）中未掌握的部分 → REVIEW_PREREQUISITE。"""
    missing: List[str] = []
    for prereq in course.all_prerequisites_transitive(target_kc):
        item = knowledge_map.get(prereq)
        if item is None or item.mastery < MASTERED_THRESHOLD:
            missing.append(prereq)
    if missing:
        reason_codes.append(REASON_LOW_PREREQUISITE_MASTERY)
        return {
            "review_prerequisite": True,
            "prerequisite_topics": missing,
            "pedagogical_actions": ["REVIEW_PREREQUISITE"] + ["EXPLAIN", "WORKED_EXAMPLE"],
            "content_order": missing + [target_kc],
        }
    return {}
