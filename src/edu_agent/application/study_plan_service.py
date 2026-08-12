"""StudyPlanService：唯一的正式学习计划实现。

generate_plan 输入：user_id / course_id / goal / duration_days / daily_minutes /
optional_background。
流程：确保课程+active goal → 构建 PlanContext（画像在计划生成前生效）→
run_study_plan_workflow → 持久化 study_plans + plan_steps → 更新目标/进度 → PLAN_CREATED。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.application.learning_context_service import resolve_bundle_and_course
from edu_agent.adaptive.plan_context import build_plan_context
from edu_agent.learner_model.service import LearnerModelService
from edu_agent.workflows.study_plan.schemas import StudentInput
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def generate_plan(
    user_id: str,
    course_id: str,
    goal: str = "",
    duration_days: Optional[int] = None,
    daily_minutes: Optional[int] = None,
    optional_background: str = "",
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """生成学习计划并持久化。

    duration_days / daily_minutes 为 Optional：未传时沿用课程已保存的默认值
    （create_course 落库的 duration_days / daily_minutes），避免每次强制 14/60 而无法区分
    「未传」与「用户显式选择默认」。
    """
    from edu_agent.application.course_service import get_course as course_get

    learner = learner or LearnerModelService()
    # ownership 优先：先确认课程属于当前 user，再 ensure_course
    # （否则非法 course_id 会经 ensure_course 产生 ghost learner_course_state）
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    learner.ensure_course(user_id, course_id)

    # 目标：一个课程一个 active goal（首次创建）
    from edu_agent.adaptive.course_resolver import resolve_goal_id

    goal_id = resolve_goal_id(user_id, course_id)
    course_info = course_get(user_id, course_id, learner)
    course_row = learner.repo.get_user_course(user_id, course_id)
    saved_days = int(course_row.get("duration_days") or 14)
    saved_minutes = int(course_row.get("daily_minutes") or 60)
    resolved_days = int(duration_days) if duration_days else saved_days
    resolved_minutes = int(daily_minutes) if daily_minutes else saved_minutes
    active_goal = course_info.get("goal")
    # goal 语义默认也用稳定 course.topic（而非 display_name），避免 rename 后
    # 计划目标/内容围绕「30天冲刺课」这类 UI label 而非真实主题。
    goal_text = goal or (active_goal or {}).get("target") or course_info.get("topic", course_id)
    if active_goal is None:
        learner.upsert_goal(user_id, goal_id, course_id, name=course_info.get("display_name", course_id),
                            target=goal_text)
        learner.set_current_goal(user_id, course_id, goal_id)

    # 首次提供背景 → USER_EXPLICIT_PROFILE_FACT（画像闭环）
    if optional_background and optional_background.strip():
        learner.set_profile_fact(user_id, f"background:{course_id}", optional_background.strip(),
                                 category="background")

    # PlanContext：画像在计划生成前生效（跳过/复习/顺序；读取 active profile facts）
    bundle, course = resolve_bundle_and_course(user_id, course_id, learner)
    plan_context = build_plan_context(
        bundle, learner.repo, course, goal=goal_text,
        daily_minutes=resolved_minutes, duration_days=resolved_days,
        user_id=user_id, course_id=course_id,
    )

    student_input = StudentInput(
        # 语义主题必须用稳定的 course.topic（rename 只改 display_name，不改 topic），
        # 否则重生成 Plan 会围绕 display_name（如「30天冲刺课」）而非真实主题。
        # UI 标题仍可显示 display_name（见下方 plan title）。
        topic=course_info.get("topic", course_id),
        level=None,
        days=resolved_days,
        daily_time=f"{resolved_minutes}分钟",
        goal=goal_text,
    )
    result = run_study_plan_workflow(
        student_input,
        plan_context=plan_context,
    )
    final_plan = result.get("final_plan", "")

    # 持久化 plan + steps（KnowledgeMap nodes → plan_steps；node.id 即 kc_id；
    # step_id 与 kc_id 分离：step_id=PLANSTEP-{uuid}，kc_id=KnowledgeNode.id）
    plan_id = f"PLAN-{uuid.uuid4().hex[:10]}"
    km = result.get("knowledge_map")
    nodes = [n.model_dump() for n in (km.nodes if km and hasattr(km, "nodes") else [])]
    summary = _plan_summary(plan_context, nodes)

    # Finalize 单事务（用户要求：LLM workflow 在事务外，返回后写入必须一个事务）：
    # delete/replace 旧 plan → insert study_plan → insert plan_steps →
    # goal target_kcs → PLAN_CREATED event。任一失败整体回滚，旧 plan 继续可用。
    # 个性化 Plan Nodes 只保存在 plan_steps（user-scoped），不写共享 domain_kcs。
    with learner.repo.transaction():
        old_plan = learner.repo.get_plan(user_id, course_id)
        if old_plan is not None:
            learner.repo.delete_plan(old_plan["plan_id"])
        # 把本次解析出的周期/每日时长写回课程，作为新的默认值（沿用或覆盖都保持一致）
        learner.repo.upsert_user_course(
            {**course_row, "duration_days": resolved_days, "daily_minutes": resolved_minutes,
             "updated_at": _now_iso()}
        )
        learner.repo.upsert_plan(
            {"plan_id": plan_id, "user_id": user_id, "course_id": course_id,
             "goal_id": goal_id, "title": f"{course_info.get('display_name', course_id)} 学习计划",
             "summary": summary, "plan_markdown": final_plan, "progress": 0.0,
             "created_at": _now_iso(), "updated_at": _now_iso()}
        )
        for idx, node in enumerate(nodes, start=1):
            learner.repo.upsert_plan_step(
                {"step_id": f"PLANSTEP-{uuid.uuid4().hex[:10]}", "plan_id": plan_id, "seq": idx,
                 "stage_id": node.get("stage_id", "stage-1"),
                 "stage_title": node.get("stage_title", ""),
                 "stage_order": int(node.get("stage_order", 1) or 1),
                 "kc_id": node.get("id") or "",
                 "title": node.get("title", ""), "description": node.get("summary", ""),
                 "learning_objective": node.get("learning_objective", ""),
                 "prerequisites_json": json.dumps(node.get("prerequisites") or [], ensure_ascii=False),
                 "difficulty": node.get("difficulty", ""),
                 "minutes": int(node.get("estimated_minutes", 30) or 30),
                 "status": "not_started", "created_at": _now_iso(), "updated_at": _now_iso()}
            )
        # plan_steps 持久化核心展示字段（title/objective/prerequisites/difficulty 已完整保存）。
        # target_kcs 记入 active goal 供上下文参考。
        if nodes:
            learner.upsert_goal(user_id, goal_id, course_id,
                                name=course_info.get("display_name", course_id), target=goal_text,
                                target_kcs=[n.get("id") for n in nodes if n.get("id")][:8] or None)
        learner.record_event({"event_type": "PLAN_CREATED", "user_id": user_id,
                              "course_id": course_id, "payload": {"plan_id": plan_id, "goal_id": goal_id}})

    return get_plan(user_id, course_id, learner)


def get_plan(user_id: str, course_id: str,
             learner: Optional[LearnerModelService] = None) -> Optional[dict]:
    """取当前课程计划（plan + 三阶段 steps）。"""
    learner = learner or LearnerModelService()
    plan = learner.repo.get_plan(user_id, course_id)
    if plan is None:
        return None
    steps = learner.repo.list_plan_steps(plan["plan_id"])
    step_dicts = [
        {
            "step_id": s["step_id"], "seq": s["seq"],
            "stage_id": s.get("stage_id", "stage-1"),
            "stage_title": s.get("stage_title", ""),
            "stage_order": s.get("stage_order", 1),
            "kc_id": s.get("kc_id", ""),
            "title": s["title"], "description": s.get("description", ""),
            "learning_objective": s.get("learning_objective", ""),
            "prerequisites": json.loads(s.get("prerequisites_json") or "[]") or [],
            "difficulty": s.get("difficulty", ""),
            "minutes": s.get("minutes", 30),
            "status": s.get("status", "not_started"),
            "lesson_markdown": s.get("lesson_markdown", "") or "",
            "lesson_generated_at": s.get("lesson_generated_at") or None,
        }
        for s in steps
    ]
    # 三阶段分组（stage_order 1→2→3；无阶段信息时兜底归为阶段 1）
    stages: Dict[int, dict] = {}
    for step in step_dicts:
        order = int(step.get("stage_order", 1) or 1)
        group = stages.setdefault(
            order,
            {"stage_id": step.get("stage_id", f"stage-{order}"),
             "stage_title": step.get("stage_title") or _DEFAULT_STAGE_TITLES.get(order, f"阶段 {order}"),
             "order": order, "steps": []},
        )
        group["steps"].append(step)
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
        "stages": [stages[order] for order in sorted(stages)],
        "steps": step_dicts,
    }


_DEFAULT_STAGE_TITLES = {1: "基础准备", 2: "核心学习", 3: "综合应用"}


def get_step(user_id: str, course_id: str, step_id: str,
             learner: Optional[LearnerModelService] = None) -> dict:
    """取单个计划步骤，并校验属于 user+course（Chat plan_step context / GET endpoint 用）。"""
    learner = learner or LearnerModelService()
    step = learner.repo.get_plan_step_by_id(user_id, course_id, step_id)
    if step is None:
        raise KeyError(f"plan step not found: {step_id}")
    return {
        "step_id": step["step_id"],
        "plan_id": step["plan_id"],
        "seq": step["seq"],
        "stage_id": step.get("stage_id", "stage-1"),
        "stage_title": step.get("stage_title", ""),
        "stage_order": step.get("stage_order", 1),
        "kc_id": step.get("kc_id", ""),
        "title": step["title"],
        "description": step.get("description", ""),
        "learning_objective": step.get("learning_objective", ""),
        "prerequisites": json.loads(step.get("prerequisites_json") or "[]") or [],
        "difficulty": step.get("difficulty", ""),
        "minutes": step.get("minutes", 30),
        "status": step.get("status", "not_started"),
        "lesson_markdown": step.get("lesson_markdown", "") or "",
        "lesson_generated_at": step.get("lesson_generated_at") or None,
        "updated_at": step.get("updated_at"),
    }


def update_step_status(
    user_id: str, course_id: str, step_id: str, status: str,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """更新计划步骤状态 → 同事务同步 plan/course/goal progress + 事件（不修改 mastery）。

    - kc_id = step.kc_id（不是 step_id）；
    - completed 只更新进度与 exposure，绝不提升 mastery。
    """
    learner = learner or LearnerModelService()
    if status not in ("not_started", "in_progress", "completed"):
        raise ValueError(f"invalid step status: {status}")
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    plan = learner.repo.get_plan(user_id, course_id)
    if plan is None:
        raise KeyError("no plan for course")
    step = learner.repo.get_plan_step(plan["plan_id"], step_id)
    if step is None:
        raise KeyError(f"step not found: {step_id}")
    old_status = step.get("status")
    kc_id = step.get("kc_id") or ""

    with learner.repo.transaction():
        learner.repo.upsert_plan_step({**step, "status": status, "updated_at": _now_iso()})
        steps = learner.repo.list_plan_steps(plan["plan_id"])
        completed = sum(1 for s in steps if s.get("status") == "completed")
        progress = round(completed / len(steps), 3) if steps else 0.0
        learner.repo.update_plan_progress(plan["plan_id"], progress)
        learner.update_course_progress(user_id, course_id, progress)
        # active goal progress 同步（唯一来源：plan steps）
        bundle = learner.build_bundle(user_id, course_id)
        if bundle.active_goal:
            learner.update_goal_progress(user_id, bundle.active_goal.goal_id, progress)

        if status == "completed" and old_status != "completed":
            learner.record_event({"event_type": "PLAN_STEP_COMPLETED", "user_id": user_id,
                                  "course_id": course_id, "kc_id": kc_id,
                                  "payload": {"step_id": step_id, "plan_id": plan["plan_id"],
                                              "progress": progress}})
        elif status == "in_progress" and old_status != "in_progress":
            learner.record_event({"event_type": "PLAN_STEP_STARTED", "user_id": user_id,
                                  "course_id": course_id, "kc_id": kc_id,
                                  "payload": {"step_id": step_id, "plan_id": plan["plan_id"]}})
    return get_plan(user_id, course_id, learner)


def _plan_summary(plan_context: Dict[str, object], nodes: List[dict]) -> str:
    note = plan_context.get("personalization_note")
    days = plan_context.get("duration_days")
    minutes = plan_context.get("daily_minutes")
    base = f"{days} 天 · 每天 {minutes} 分钟 · {len(nodes)} 个学习步骤"
    return f"{base}；{note}" if note else base


# ---------------------------------------------------------------------------
# Plan Step Lesson（懒生成：首次「开始学习 / 继续学习」才调 LLM，不污染 generate_plan）
# ---------------------------------------------------------------------------

_LESSON_SYSTEM = (
    "你是 EduAgents 的课程讲解助手。围绕当前学习计划的一个知识点，"
    "生成可以直接阅读学习的教学内容。不能只是重复标题、目标、描述，必须真正解释知识。\n"
    "使用标准 Markdown；代码必须用 fenced code block；行内数学用 $...$，块级用 $$...$$。\n"
    "禁止输出练习题、测试题、测验或自动判题；可以用示例、Worked Example、代码演示、案例与总结。"
)


def get_or_generate_step_lesson(
    user_id: str, course_id: str, step_id: str,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """GET-OR-GENERATE 单个 plan step 的讲解（lesson_markdown）。

    - 已有 lesson_markdown → 直接返回（不再调 LLM）。
    - 没有 → 收集上下文（课程名/目标/阶段/step 字段/PlanContext 画像/课程 RAG）→
      LLM 生成。LLM 在事务外运行；返回后重验证 step 仍属于当前 user/course/current plan，
      再落库 lesson_markdown + lesson_generated_at。
    - 不更新 mastery；LLM 失败不保存错误正文（调用方据此返回 5xx，前端重试）。
    """
    learner = learner or LearnerModelService()
    # ownership：先确认课程归属，再查 step（避免 ghost state / 越权读他人 step）
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    step = learner.repo.get_plan_step_by_id(user_id, course_id, step_id)
    if step is None:
        raise KeyError(f"plan step not found: {step_id}")

    existing = (step.get("lesson_markdown") or "").strip()
    if existing:
        return _lesson_payload(step, existing)

    context_text = _build_lesson_context(user_id, course_id, step, learner)
    markdown = _generate_lesson_markdown(step, context_text)
    if not markdown or not markdown.strip():
        raise RuntimeError("lesson generation returned empty content")

    # Stale 保护：重验证 step 仍属于当前 user/course/current plan 后再写。
    # 必须以「重读后的 fresh」为基准落库，而非最初的 step snapshot——
    # 否则 Lesson 生成期间 step status 从 in_progress 变为 completed 会被旧 snapshot 回滚。
    fresh = learner.repo.get_plan_step_by_id(user_id, course_id, step_id)
    if fresh is None or fresh.get("plan_id") != step.get("plan_id"):
        raise RuntimeError("plan step changed during lesson generation; discard stale lesson")

    generated_at = _now_iso()
    with learner.repo.transaction():
        learner.repo.upsert_plan_step(
            {**fresh, "lesson_markdown": markdown, "lesson_generated_at": generated_at,
             "updated_at": generated_at}
        )
    return _lesson_payload(fresh, markdown, generated_at)


def _lesson_payload(step: dict, markdown: str, generated_at: Optional[str] = None) -> dict:
    return {
        "step_id": step["step_id"],
        "lesson_markdown": markdown,
        "lesson_generated_at": generated_at or step.get("lesson_generated_at") or _now_iso(),
        "title": step.get("title", ""),
    }


def _build_lesson_context(
    user_id: str, course_id: str, step: dict, learner: "LearnerModelService"
) -> str:
    """构建讲解上下文：课程名 / 目标 / 阶段 / step 字段 / PlanContext 画像 / 课程 RAG。"""
    lines: List[str] = []
    try:
        course_row = learner.repo.get_user_course(user_id, course_id)
        course_title = (course_row or {}).get("display_name") or course_id
        lines.append(f"课程：{course_title}")
        # 课程已真实保存周期/每日时长 → Lesson 个性化与 Plan 生成使用同一配置
        resolved_days = int((course_row or {}).get("duration_days") or 14)
        resolved_minutes = int((course_row or {}).get("daily_minutes") or 60)
        goal = learner.resolve_active_goal(user_id, course_id)
        if goal:
            g = (goal.target or goal.goal_name or "")
            if g:
                lines.append(f"学习目标：{g}")

        bundle, course = resolve_bundle_and_course(user_id, course_id, learner)
        pc = build_plan_context(
            bundle, learner.repo, course,
            goal=(goal.target or goal.goal_name or ""),
            daily_minutes=resolved_minutes, duration_days=resolved_days,
            user_id=user_id, course_id=course_id,
        )
        if pc.get("background_facts"):
            lines.append("学习者背景：" + "；".join(pc["background_facts"]))
        if pc.get("preferred_style"):
            lines.append(f"偏好风格：{pc['preferred_style']}")

        # 课程 RAG（可选；失败不影响生成）
        try:
            from edu_agent.tools import kb_store
            from edu_agent.tools.course_kb import CourseKnowledgeBase

            chunks = kb_store.load_chunks(course_id)
            if chunks:
                kb = CourseKnowledgeBase.from_chunks(chunks, course_id=course_id)
                hits = kb.search(
                    f"{step.get('title', '')} {step.get('learning_objective', '')}", top_k=3
                )
                if hits:
                    lines.append(
                        "相关资料：\n"
                        + "\n".join(f"- {h.doc_title}: {h.text[:300]}" for h in hits)
                    )
        except Exception:  # noqa: BLE001
            logger.warning("[lesson] rag failed: course=%s", course_id, exc_info=True)
    except Exception:  # noqa: BLE001 - 个性化失败只丢个性化字段
        logger.warning("[lesson] context build degraded", exc_info=True)
        course_row = learner.repo.get_user_course(user_id, course_id)
        lines.append(f"课程：{(course_row or {}).get('display_name') or course_id}")

    lines.append("知识点信息：")
    lines.append(f"- 标题：{step.get('title', '')}")
    if step.get("description"):
        lines.append(f"- 描述：{step['description']}")
    if step.get("learning_objective"):
        lines.append(f"- 学习目标：{step['learning_objective']}")
    pres = json.loads(step.get("prerequisites_json") or "[]") or []
    if pres:
        lines.append("- 前置：" + "、".join(pres))
    if step.get("difficulty"):
        lines.append(f"- 难度：{step['difficulty']}")
    if step.get("minutes"):
        lines.append(f"- 建议时长：{step['minutes']} 分钟")
    if step.get("stage_title"):
        lines.append(f"- 所属阶段：{step['stage_title']}")
    return "\n".join(lines)


def _generate_lesson_markdown(step: dict, context_text: str) -> str:
    """调用 LLM 生成讲解 Markdown（结构与长度遵循需求）。"""
    from edu_agent.core.agent_runner import model_to_text
    from edu_agent.core.llm import get_kb_llm
    from langchain_core.prompts import ChatPromptTemplate

    minutes = int(step.get("minutes") or 30)
    length_note = "约 500–1200 中文字" if minutes <= 30 else "可更详细并带示例"
    template = (
        "{system}\n\n{context}\n\n知识点信息如上。请按以下结构输出 Markdown 讲解"
        f"（{length_note}）：\n"
        "## 本节要学什么\n## 核心讲解\n## 关键点\n## 示例\n## 常见误区\n"
        "## 实际应用\n## 本节总结"
    )
    prompt = ChatPromptTemplate.from_template(template)
    response = (prompt | get_kb_llm(temperature=0.4)).invoke(
        {"system": _LESSON_SYSTEM, "context": context_text}
    )
    return model_to_text(response).strip()
