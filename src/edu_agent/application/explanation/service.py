"""ExplanationService：结构化讲解的存取 + 懒生成 + 缓存 + 失效。

- get_explanation：GET-OR-GENERATE。context_hash 不变 → 复用缓存；
  hash 变化 → 重新生成（避免每次页面刷新调 LLM，也避免 mastery 微小变化重生成全文）。
- invalidate_explanation：删除课程 / 重新生成计划时清理。
- 校验：kc_id 必须存在于 active graph；block 必须通过 ExplanationValidator。

不生成 exercise / 不判题（见 tests/test_no_exercise.py）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from edu_agent.application.explanation.context_builder import ExplanationContext, ExplanationContextBuilder
from edu_agent.application.explanation.generator import (
    generate_explanation,
    _deduplicate_blocks,
    _normalize_block,
    _validate_trie_prefix_diagrams,
)
from edu_agent.application.explanation.models import PracticeHandoff, StepExplanation
from edu_agent.application.explanation.validator import ExplanationValidator
from edu_agent.application.course_graph_service import CourseGraphService
from edu_agent.domain.learning.course import Course
from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger("edu_agent.application.explanation.service")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class ExplanationService:
    def __init__(
        self,
        learner: LearnerModelService,
        context_builder: Optional[ExplanationContextBuilder] = None,
    ) -> None:
        self.learner = learner
        self.graph_service = CourseGraphService(learner._repo)
        self.context_builder = context_builder or ExplanationContextBuilder(
            learner, graph_service=self.graph_service
        )
        self.validator = ExplanationValidator()

    # ------------------------------------------------------------------
    # 读取（懒生成 + 缓存）
    # ------------------------------------------------------------------
    def get_explanation(
        self, user_id: str, course_id: str, plan_id: str, step_id: str
    ) -> dict:
        if self.learner.repo.get_user_course(user_id, course_id) is None:
            raise KeyError(f"course not found: {course_id}")
        step = self.learner.repo.get_plan_step_by_id(user_id, course_id, step_id)
        if step is None:
            raise KeyError(f"plan step not found: {step_id}")

        course = self._load_course(user_id, course_id)
        kc_id = step.get("kc_id") or ""
        if kc_id and course.kc_by_id(kc_id) is None:
            raise KeyError(f"kc not found in course graph: {kc_id}")

        ctx = self.context_builder.build(user_id, course_id, course, plan_id, step)
        existing = self.learner.repo.get_step_explanation(user_id, course_id, step_id)
        if existing is not None:
            if existing.get("context_hash") == ctx.context_hash and int(existing.get("schema_version") or 1) >= 2:
                return self._hydrate(existing, step, kc_id, ctx)
            # context 或 schema 变化 → 重新生成，避免继续返回旧的短卡片内容。
            logger.info(
                "explanation cache stale (context/schema changed); regenerate step=%s", step_id
            )

        explanation = generate_explanation(
            ctx, plan_id=plan_id,
        )
        explanation.step_id = step_id
        issues = self.validator.validate(explanation)
        if issues:
            logger.warning("explanation validation issues: %s",
                           [i.message for i in issues])
        self._persist(user_id, course_id, step_id, explanation)
        return self._to_dict(explanation, step)

    # ------------------------------------------------------------------
    # 失效
    # ------------------------------------------------------------------
    def invalidate_explanation(self, user_id: str, course_id: str) -> None:
        self.learner.repo.delete_step_explanations(user_id, course_id)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _load_course(self, user_id: str, course_id: str) -> Course:
        active = self.graph_service.load_active_graph(user_id, course_id)
        if active is None:
            raise KeyError(f"course graph not found: {course_id}")
        return active.course

    def _persist(self, user_id: str, course_id: str, step_id: str,
                 explanation: StepExplanation) -> None:
        now = _now_iso()
        self.learner.repo.upsert_step_explanation(
            {
                "explanation_id": explanation.explanation_id,
                "user_id": user_id,
                "course_id": course_id,
                "plan_id": explanation.plan_id,
                "step_id": step_id,
                "kc_id": explanation.kc_id,
                "schema_version": explanation.schema_version,
                "content_json": json.dumps(explanation.model_dump(mode="json"), ensure_ascii=False),
                "context_hash": explanation.context_hash,
                "generated_at": now,
                "updated_at": now,
            }
        )

    def _hydrate(
        self, row: dict, step: dict, kc_id: str, ctx: ExplanationContext
    ) -> dict:
        try:
            content = json.loads(row.get("content_json") or "{}")
        except json.JSONDecodeError:
            content = {}
        explanation = StepExplanation(**content)
        # Normalization rules may improve independently of the generated
        # facts. Repair cached Markdown/LaTeX on read instead of spending a
        # second full model generation for a presentation-only correction.
        explanation.blocks = _deduplicate_blocks(
            [_normalize_block(block) for block in explanation.blocks]
        )
        _validate_trie_prefix_diagrams(ctx, explanation.blocks)
        explanation.step_id = step.get("step_id", "")
        return self._to_dict(explanation, step)

    def _to_dict(self, explanation: StepExplanation, step: dict) -> dict:
        return {
            "step_id": step.get("step_id", ""),
            "plan_id": explanation.plan_id,
            "kc_id": explanation.kc_id,
            "title": explanation.title,
            "objective": explanation.objective,
            "estimated_minutes": explanation.estimated_minutes,
            "schema_version": explanation.schema_version,
            "blocks": [b.model_dump(mode="json") for b in explanation.blocks],
            "context_hash": explanation.context_hash,
            "generated_at": explanation.generated_at,
        }


# ---------------------------------------------------------------------------
# Practice Handoff（只定义接口，不实现练习）
# ---------------------------------------------------------------------------


def build_practice_handoff(
    user_id: str, course_id: str, plan_id: str, step_id: str,
    learner: LearnerModelService,
) -> PracticeHandoff:
    step = learner.repo.get_plan_step_by_id(user_id, course_id, step_id)
    if step is None:
        raise KeyError(f"plan step not found: {step_id}")
    return PracticeHandoff(
        course_id=course_id,
        plan_id=plan_id,
        step_id=step_id,
        kc_id=step.get("kc_id", ""),
        learning_objective=step.get("learning_objective", ""),
        recommended_difficulty=step.get("difficulty") or "medium",
        source="study_plan",
        return_url="",
    )
