"""StudyPlanService：唯一的正式学习计划实现。

generate_plan 输入：user_id / course_id / goal / duration_days / daily_minutes /
optional_background / optional_extra_requirement。
流程：确保课程+active goal → 构建 PlanContext（画像在计划生成前生效）→
run_study_plan_workflow → 持久化 study_plans + plan_steps → 更新目标/进度 → PLAN_CREATED。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.application.learning_context_service import resolve_bundle_and_course
from edu_agent.adaptive.plan_context import build_plan_context
from edu_agent.learner_model.service import LearnerModelService
from edu_agent.workflows.study_plan.schemas import StudentInput
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def generate_plan(
    user_id: str,
    course_id: str,
    goal: str = "",
    duration_days: int = 14,
    daily_minutes: int = 60,
    optional_background: str = "",
    optional_extra_requirement: str = "",
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """生成学习计划并持久化。"""
    from edu_agent.application.course_service import get_course as course_get

    learner = learner or LearnerModelService()
    learner.ensure_course(user_id, course_id)

    # 目标：一个课程一个 active goal（首次创建）
    from edu_agent.adaptive.course_resolver import resolve_goal_id

    goal_id = resolve_goal_id(user_id, course_id)
    course_info = course_get(user_id, course_id, learner)
    active_goal = course_info.get("goal")
    goal_text = goal or (active_goal or {}).get("target") or course_info.get("display_name", course_id)
    if active_goal is None:
        learner.upsert_goal(user_id, goal_id, course_id, name=course_info.get("display_name", course_id),
                            target=goal_text)
        learner.set_current_goal(user_id, course_id, goal_id)

    # 首次提供背景 → USER_EXPLICIT_PROFILE_FACT（画像闭环）
    if optional_background and optional_background.strip():
        learner.set_profile_fact(user_id, f"background:{course_id}", optional_background.strip(),
                                 category="background")

    # PlanContext：画像在计划生成前生效（跳过/复习/顺序）
    bundle, course = resolve_bundle_and_course(user_id, course_id, learner)
    plan_context = build_plan_context(
        bundle, course, goal=goal_text,
        daily_minutes=int(daily_minutes), duration_days=int(duration_days),
    )

    student_input = StudentInput(
        topic=course_info.get("display_name", course_id),
        level=None,
        days=int(duration_days),
        daily_time=f"{int(daily_minutes)}分钟",
        goal=goal_text,
    )
    result = run_study_plan_workflow(
        student_input,
        learner_context="",
        adaptive_instructions="",
        plan_context=plan_context,
    )
    final_plan = result.get("final_plan", "")

    # 持久化 plan + steps（KnowledgeMap nodes → plan_steps；node.id 即 kc_id）
    plan_id = f"PLAN-{uuid.uuid4().hex[:10]}"
    km = result.get("knowledge_map")
    nodes = [n.model_dump() for n in (km.nodes if km and hasattr(km, "nodes") else [])]
    summary = _plan_summary(plan_context, nodes)
    learner.repo.upsert_plan(
        {"plan_id": plan_id, "user_id": user_id, "course_id": course_id,
         "goal_id": goal_id, "title": f"{course_info.get('display_name', course_id)} 学习计划",
         "summary": summary, "plan_markdown": final_plan, "progress": 0.0,
         "created_at": _now_iso(), "updated_at": _now_iso()}
    )
    for idx, node in enumerate(nodes, start=1):
        learner.repo.upsert_plan_step(
            {"step_id": node.get("id") or f"step-{idx}", "plan_id": plan_id, "seq": idx,
             "title": node.get("title", ""), "description": node.get("summary", ""),
             "minutes": int(node.get("estimated_minutes", 30) or 30),
             "status": "not_started", "created_at": _now_iso(), "updated_at": _now_iso()}
        )

    # 目标 target_kcs + 课程 Domain 注册
    if nodes:
        from edu_agent.domain.learning.course_builder import (
            build_course_from_nodes,
            load_course_from_repo,
            persist_course,
        )
        from edu_agent.domain.learning.kc_graph import register_course

        course_obj = build_course_from_nodes(course_id, course_info.get("display_name", course_id),
                                             nodes, topic=course_info.get("topic", ""))
        register_course(course_obj)
        persist_course(learner.repo, course_obj, topic=course_info.get("topic", ""))
        learner.upsert_goal(user_id, goal_id, course_id,
                            name=course_info.get("display_name", course_id), target=goal_text,
                            target_kcs=[n.get("id") for n in nodes if n.get("id")][:8] or None)
    learner.record_event({"event_type": "PLAN_CREATED", "user_id": user_id,
                          "course_id": course_id, "payload": {"plan_id": plan_id, "goal_id": goal_id}})

    return get_plan(user_id, course_id, learner)


def get_plan(user_id: str, course_id: str,
             learner: Optional[LearnerModelService] = None) -> Optional[dict]:
    """取当前课程计划（plan + steps）。"""
    learner = learner or LearnerModelService()
    plan = learner.repo.get_plan(user_id, course_id)
    if plan is None:
        return None
    steps = learner.repo.list_plan_steps(plan["plan_id"])
    return {
        "plan_id": plan["plan_id"],
        "course_id": plan["course_id"],
        "goal_id": plan.get("goal_id", ""),
        "title": plan.get("title", ""),
        "summary": plan.get("summary", ""),
        "plan_markdown": plan.get("plan_markdown", ""),
        "progress": float(plan.get("progress", 0.0)),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "steps": [
            {"step_id": s["step_id"], "seq": s["seq"], "title": s["title"],
             "description": s.get("description", ""), "minutes": s.get("minutes", 30),
             "status": s.get("status", "not_started")}
            for s in steps
        ],
    }


def update_step_status(
    user_id: str, course_id: str, step_id: str, status: str,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """更新计划步骤状态 → 重算进度（不修改 mastery）。"""
    learner = learner or LearnerModelService()
    if status not in ("not_started", "in_progress", "completed"):
        raise ValueError(f"invalid step status: {status}")
    plan = learner.repo.get_plan(user_id, course_id)
    if plan is None:
        raise KeyError("no plan for course")
    step = learner.repo.get_plan_step(plan["plan_id"], step_id)
    if step is None:
        raise KeyError(f"step not found: {step_id}")
    old_status = step.get("status")
    learner.repo.upsert_plan_step({**step, "status": status, "updated_at": _now_iso()})

    steps = learner.repo.list_plan_steps(plan["plan_id"])
    completed = sum(1 for s in steps if s.get("status") == "completed")
    progress = round(completed / len(steps), 3) if steps else 0.0
    learner.repo.update_plan_progress(plan["plan_id"], progress)
    learner.update_course_progress(user_id, course_id, progress)

    if status == "completed" and old_status != "completed":
        learner.record_event({"event_type": "PLAN_STEP_COMPLETED", "user_id": user_id,
                              "course_id": course_id, "kc_id": step_id,
                              "payload": {"step_id": step_id, "progress": progress}})
    elif status == "in_progress" and old_status != "in_progress":
        learner.record_event({"event_type": "PLAN_STEP_STARTED", "user_id": user_id,
                              "course_id": course_id, "kc_id": step_id,
                              "payload": {"step_id": step_id}})
    return get_plan(user_id, course_id, learner)


def _plan_summary(plan_context: Dict[str, object], nodes: List[dict]) -> str:
    note = plan_context.get("personalization_note")
    days = plan_context.get("duration_days")
    minutes = plan_context.get("daily_minutes")
    base = f"{days} 天 · 每天 {minutes} 分钟 · {len(nodes)} 个学习步骤"
    return f"{base}；{note}" if note else base
