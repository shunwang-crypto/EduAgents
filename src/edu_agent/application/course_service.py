"""CourseService：课程管理（创建/查看/切换/重命名/删除/解析）。

课程信息组合：domain_courses（标题/主题）+ learner_course_states（进度）+
learning_goals（目标）+ study_plans（计划摘要）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from edu_agent.adaptive.course_resolver import resolve_course_id, resolve_goal_id
from edu_agent.learner_model.service import LearnerModelService


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def list_courses(user_id: str, learner: Optional[LearnerModelService] = None) -> List[dict]:
    """列出用户课程（含 goal/进度/计划摘要）。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    courses = learner.repo.list_domain_courses()
    result = []
    for c in courses:
        course_id = c["course_id"]
        result.append(_compose_course(user_id, course_id, c, learner))
    return result


def create_course(
    user_id: str,
    topic: str,
    goal: str = "",
    duration_days: int = 14,
    daily_minutes: int = 60,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """按主题创建课程：resolve course_id → 建 domain_course + course_state + active goal。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    existing_ids = [c["course_id"] for c in learner.repo.list_domain_courses()]
    course_id = resolve_course_id(topic, existing_ids)

    if learner.repo.get_domain_course(course_id) is None:
        learner.repo.upsert_domain_course(
            {"course_id": course_id, "title": topic.strip(), "topic": topic.strip(),
             "created_at": _now_iso()}
        )
    learner.ensure_course(user_id, course_id)

    # 一个课程一个 active goal（旧 active → completed）
    for g in learner.repo.list_goals(user_id, status="active"):
        if g.get("course_id") == course_id and g["goal_id"] != resolve_goal_id(user_id, course_id):
            learner.set_goal_status(user_id, g["goal_id"], "completed")

    goal_id = resolve_goal_id(user_id, course_id)
    learner.upsert_goal(user_id, goal_id, course_id, name=topic.strip(), target=goal or "")
    learner.set_current_goal(user_id, course_id, goal_id)
    learner.record_event({"event_type": "COURSE_CREATED", "user_id": user_id,
                          "course_id": course_id, "payload": {"topic": topic.strip()}})

    return get_course(user_id, course_id, learner)


def get_course(user_id: str, course_id: str,
               learner: Optional[LearnerModelService] = None) -> dict:
    learner = learner or LearnerModelService()
    row = learner.repo.get_domain_course(course_id)
    if row is None:
        # 兼容：内置课程（JAVA-OOP/TRANSFORMER）未持久化时按需建立
        from edu_agent.domain.learning.kc_graph import get_course as builtin

        builtin_course = builtin(course_id)
        if builtin_course is None:
            raise KeyError(f"course not found: {course_id}")
        row = {"course_id": course_id, "title": builtin_course.title,
               "topic": builtin_course.title, "created_at": _now_iso()}
        learner.repo.upsert_domain_course(row)
    return _compose_course(user_id, course_id, row, learner)


def rename_course(user_id: str, course_id: str, new_title: str,
                  learner: Optional[LearnerModelService] = None) -> dict:
    learner = learner or LearnerModelService()
    row = learner.repo.get_domain_course(course_id)
    if row is None:
        raise KeyError(f"course not found: {course_id}")
    learner.repo.upsert_domain_course({**row, "title": new_title.strip() or row["title"]})
    learner.record_event({"event_type": "COURSE_UPDATED", "user_id": user_id,
                          "course_id": course_id, "payload": {"title": new_title}})
    return get_course(user_id, course_id, learner)


def delete_course(user_id: str, course_id: str,
                  learner: Optional[LearnerModelService] = None) -> None:
    """真正删除课程：domain_course 及关联 KC/关系、目标置 cancelled（events 保留审计）。"""
    learner = learner or LearnerModelService()
    learner.repo.delete_domain_course(course_id)
    for g in learner.repo.list_goals(user_id):
        if g.get("course_id") == course_id:
            learner.repo.upsert_goal({**g, "status": "cancelled", "updated_at": _now_iso()})
    learner.record_event({"event_type": "COURSE_DELETED", "user_id": user_id,
                          "course_id": course_id, "payload": {}})


def _compose_course(user_id: str, course_id: str, row: dict,
                    learner: LearnerModelService) -> dict:
    state = learner.repo.get_course_state(user_id, course_id) or {}
    goal = None
    for g in learner.repo.list_goals(user_id, status="active"):
        if g.get("course_id") == course_id:
            try:
                target_kcs = json.loads(g.get("target_kcs_json") or "[]")
            except (ValueError, TypeError):
                target_kcs = []
            goal = {"goal_id": g["goal_id"], "name": g.get("name"),
                    "target": g.get("target", ""), "progress": float(g.get("progress", 0.0)),
                    "target_kcs": target_kcs}
            break
    plan = learner.repo.get_plan(user_id, course_id)
    return {
        "course_id": course_id,
        "display_name": row.get("title") or course_id,
        "topic": row.get("topic", ""),
        "goal": goal,
        "progress": float(state.get("progress", 0.0)),
        "plan_summary": (plan or {}).get("summary", ""),
        "created_at": row.get("created_at"),
        "updated_at": state.get("updated_at"),
    }


def parse_course_intent(text: str) -> Dict[str, Any]:
    """自然语言解析课程意图（topic/goal/duration/daily），复用 study_plan input_parser。"""
    from edu_agent.workflows.study_plan.input_parser import parse_student_input

    parsed = parse_student_input(text)
    return {
        "topic": parsed.topic or text.strip(),
        "goal": parsed.goal or "",
        "duration_days": parsed.days or 14,
        "daily_minutes": _parse_minutes(parsed.daily_time),
    }


def _parse_minutes(daily_time: str) -> int:
    import re

    if not daily_time:
        return 60
    m = re.search(r"(\d+)\s*(小时|h|hour)", daily_time, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(分钟|min|分钟)", daily_time, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 60
