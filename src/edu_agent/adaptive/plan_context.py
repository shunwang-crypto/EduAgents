"""PlanContext：学习计划自适应上下文（生成前构建，注入 plan workflow）。

不暴露 mastery 原始值 / reason_codes / policy JSON；
只输出计划生成需要的高层结论（known / unknown / review / background / style）。

background 必须读取 active profile facts（skill:* / background:{course} / no_*），
转换成人类可读摘要（background_facts），禁止把 fact_value_json 原样堆给 LLM。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.fact_text import humanize_profile_fact
from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import LearnerStateBundle

MASTERED_THRESHOLD = 0.7


def _kc_status(mastery: Optional[float], confidence: Optional[float]) -> str:
    if mastery is None:
        return "unknown"
    if mastery >= MASTERED_THRESHOLD and confidence is not None and confidence >= 0.5:
        return "known"
    if mastery >= MASTERED_THRESHOLD:
        return "known_low_conf"
    if confidence is not None and confidence >= 0.5:
        return "weak"  # 已知低掌握
    return "unknown"


def build_plan_context(
    bundle: LearnerStateBundle,
    repo: LearnerRepository,
    course: Optional[Course] = None,
    goal: str = "",
    daily_minutes: int = 60,
    duration_days: int = 14,
    user_id: str = "",
    course_id: str = "",
) -> Dict[str, object]:
    """构建 PlanContext（只含必要信息，不塞整份 Learner Model）。"""
    known: List[str] = []
    unknown: List[str] = []
    review: List[str] = []

    course_kcs = {kc.kc_id: kc for kc in bundle.course_state.knowledge}
    if course:
        for kc in course.components:
            state = course_kcs.get(kc.kc_id)
            mastery = state.mastery if state else None
            confidence = state.confidence if state else None
            status = _kc_status(mastery, confidence)
            title = kc.title or kc.kc_id
            if status == "known":
                known.append(title)
            elif status == "weak":
                review.append(title)
            else:
                unknown.append(title)
    else:
        # 无领域课程：从 bundle 知识快照尽力推导
        for item in bundle.course_state.knowledge:
            status = _kc_status(item.mastery, item.confidence)
            name = item.name or item.kc_id
            if status == "known":
                known.append(name)
            elif status == "weak":
                review.append(name)
            else:
                unknown.append(name)

    # Profile Facts → 人类可读 background_facts（共享 helper，不把内部键/JSON 给 LLM）
    background_facts: List[str] = []
    if user_id and repo is not None:
        for f in repo.list_profile_facts(user_id):
            if f.get("status") != "active":
                continue
            key = f.get("fact_key", "")
            if not key:
                continue
            # 课程级 background 只进对应课程；其他课程 background 不污染
            if key.startswith("background:") and key != f"background:{course_id}":
                continue
            background_facts.append(humanize_profile_fact(key, f.get("fact_value_json")))
    # 课程级 background fact 优先展示，global 无重复
    prefs = bundle.global_state.preferences
    preferred_style = prefs.preferred_mode or ""
    memories = [m.content for m in bundle.global_state.semantic_memory[:3]]

    return {
        "goal": goal,
        "known_topics": known[:10],
        "unknown_topics": unknown[:10],
        "topics_needing_review": review[:10],
        "background": "；".join(background_facts),
        "background_facts": background_facts,
        "preferred_style": preferred_style,
        "semantic_memories": memories,
        "daily_minutes": daily_minutes,
        "duration_days": duration_days,
        "personalization_note": _personalization_note(known, unknown, review, background_facts),
    }


def _personalization_note(known: List[str], unknown: List[str], review: List[str],
                          background_facts: List[str]) -> str:
    parts = []
    if background_facts:
        parts.append(f"已根据你的背景（{'、'.join(background_facts[:3])}）调整基础内容")
    if known:
        parts.append(f"已根据你的背景跳过/压缩「{'、'.join(known[:3])}」的基础入门")
    if review:
        parts.append(f"计划将安排「{'、'.join(review[:3])}」的复习")
    if unknown:
        parts.append(f"「{'、'.join(unknown[:3])}」将作为新内容按顺序学习")
    return "；".join(parts) if parts else ""
