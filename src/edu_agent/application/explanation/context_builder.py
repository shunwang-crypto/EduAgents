"""ExplanationContextBuilder：为生成结构化讲解收集上下文。

输入：course goal / KC / prerequisites / step objective / learner background /
known skills / preferences / 课程资料 RAG / learner misconceptions。

输出：确定性的 ``ExplanationContext``（含 stable context_hash）。
避免 ExplanationService 变成第二个 God Service。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger("edu_agent.application.explanation.context")


@dataclass
class ExplanationContext:
    course_id: str
    course_title: str
    goal: str
    kc_id: str
    kc_title: str
    kc_description: str
    kc_category: str
    kc_difficulty: str
    prerequisites: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    step_title: str = ""
    step_objective: str = ""
    step_minutes: int = 30
    background_facts: List[str] = field(default_factory=list)
    preferred_style: str = ""
    known_topics: List[str] = field(default_factory=list)
    misconceptions: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)
    context_hash: str = ""

    def to_text(self) -> str:
        lines = [
            f"课程：{self.course_title}",
            f"学习目标：{self.goal}" if self.goal else "学习目标：（未提供）",
            f"知识点：{self.kc_title}（{self.kc_id}）",
        ]
        if self.kc_description:
            lines.append(f"描述：{self.kc_description}")
        if self.prerequisites:
            lines.append("前置：" + "、".join(self.prerequisites))
        if self.dependents:
            lines.append("后继/作用到：" + "、".join(self.dependents))
        if self.step_objective:
            lines.append(f"本步骤学习目标：{self.step_objective}")
        if self.background_facts:
            lines.append("学习者背景：" + "；".join(self.background_facts[:6]))
        if self.known_topics:
            lines.append("已了解/可跳过：" + "、".join(self.known_topics[:6]))
        if self.preferred_style:
            lines.append(f"偏好风格：{self.preferred_style}")
        if self.misconceptions:
            lines.append("学习者已有误区：" + "、".join(self.misconceptions[:4]))
        return "\n".join(lines)


class ExplanationContextBuilder:
    def __init__(self, learner: LearnerModelService, graph_service=None) -> None:
        self.learner = learner
        self._graph_service = graph_service

    def build(
        self,
        user_id: str,
        course_id: str,
        course: Course,
        plan_id: str,
        step: dict,
    ) -> ExplanationContext:
        kc = course.kc_by_id(step.get("kc_id") or "")
        kc_id = kc.kc_id if kc else (step.get("kc_id") or "")
        kc_title = kc.title if kc else (step.get("title") or kc_id)

        bundle = self.learner.build_bundle(user_id, course_id)
        goal_text = ""
        if bundle.active_goal is not None:
            goal_text = (bundle.active_goal.target or bundle.active_goal.goal_name or "").strip()
        goal_text = goal_text or course.goal

        # learner 画像（稳定背景，不依赖实时 mastery）
        background_facts: List[str] = []
        known_topics: List[str] = []
        preferred_style = ""
        try:
            facts = self.learner.list_profile_facts(user_id) if hasattr(
                self.learner, "list_profile_facts"
            ) else []
            for f in facts:
                value = f.get("value", "")
                cat = str(f.get("category", "") or "")
                if not value:
                    continue
                if cat == "background":
                    background_facts.append(value)
                    known_topics.append(value)
                elif cat.startswith("style"):
                    preferred_style = value
        except Exception:  # noqa: BLE001
            logger.warning("context: profile facts unavailable", exc_info=True)

        # misconceptions：只消费 Learner Model（不判题）
        misconceptions: List[str] = []
        knowledge = bundle.course_state.knowledge
        for item in knowledge:
            if item.kc_id == kc_id and getattr(item, "misconceptions", None):
                misconceptions = list(item.misconceptions)[:4]

        # course RAG：给讲解 grounded context（不生成练习）
        source_refs: List[str] = []
        try:
            from edu_agent.application.course_source_service import load_ready_course_chunks
            from edu_agent.tools.course_kb import CourseKnowledgeBase

            chunks = load_ready_course_chunks(user_id, course_id, learner=self.learner)
            if chunks:
                kb = CourseKnowledgeBase.from_chunks(chunks, user_id=user_id, course_id=course_id)
                hits = kb.search(f"{kc_title} {step.get('learning_objective','')}", top_k=4)
                for h in hits:
                    ref = h.source_url or h.doc_title or ""
                    if ref:
                        source_refs.append(ref)
        except Exception:  # noqa: BLE001
            logger.warning("explanation: rag unavailable", exc_info=True)

        ctx = ExplanationContext(
            course_id=course_id,
            course_title=course.title or course_id,
            goal=goal_text,
            kc_id=kc_id,
            kc_title=kc_title,
            kc_description=kc.description if kc else "",
            kc_category=kc.category if kc else "core",
            kc_difficulty=kc.difficulty if kc else "medium",
            prerequisites=course.prerequisites(kc_id),
            dependents=course.dependents(kc_id),
            step_title=step.get("title", ""),
            step_objective=step.get("learning_objective", ""),
            step_minutes=int(step.get("minutes") or 30),
            background_facts=background_facts,
            preferred_style=preferred_style,
            known_topics=known_topics,
            misconceptions=misconceptions,
            source_refs=source_refs[:6],
        )
        ctx.context_hash = self.compute_hash(ctx)
        return ctx

    @staticmethod
    def compute_hash(ctx: "ExplanationContext") -> str:
        """context_hash：plan_version + step_id + kc_id + source_version + stable background。

        只有影响讲解主体稳定性的输入参与 hash；实时 mastery 不参与，
        避免 mastery 微小变化就重生成整篇讲解。
        """
        sig = {
            "course_id": ctx.course_id,
            "kc_id": ctx.kc_id,
            "step_title": ctx.step_title,
            "step_objective": ctx.step_objective,
            "goal": ctx.goal,
            "prerequisites": ctx.prerequisites,
            "known_topics": ctx.known_topics,
            "preferred_style": ctx.preferred_style,
        }
        raw = json.dumps(sig, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
