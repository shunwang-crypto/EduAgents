"""CourseService：用户课程管理（创建/查看/重命名/删除/自然语言解析）。

User Course（user_courses 表）= 用户拥有/创建/加入的课程，按 user_id 严格隔离；
与共享 Built-in Domain Template（kc_graph.py 纯代码模板，只读）严格分离。
domain_courses/domain_kcs 已删除：个性化 Plan Nodes 只存在 plan_steps。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from edu_agent.adaptive.course_resolver import resolve_course_id, resolve_goal_id
from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _normalize_topic(topic: str) -> str:
    """主题规范化：小写 + 非字母数字中文替换为连字符（同用户去重用）。"""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", topic.strip().lower()).strip("-")
    return slug[:48] or "unknown"


def list_courses(user_id: str, learner: Optional[LearnerModelService] = None) -> List[dict]:
    """列出当前用户课程（user_courses WHERE user_id，禁止全局 domain 列表）。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    courses = learner.repo.list_user_courses(user_id)
    return [_compose_course(user_id, c["course_id"], c, learner) for c in courses]


def create_course(
    user_id: str,
    topic: str,
    goal: str = "",
    duration_days: int = 14,
    daily_minutes: int = 60,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """按主题创建用户课程：同用户同主题复用；写入 user_courses（不写共享 domain）。

    支持自然语言（方案 B）："我想两周学习 Python 数据分析，每天 1 小时"
    → 内部 parse_course_intent 提取 topic/goal/days/minutes。
    """
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic is required")
    if _looks_like_natural_language(topic):
        intent = parse_course_intent(topic)
        topic = intent["topic"] or topic
        goal = goal or intent["goal"] or ""
        duration_days = intent["duration_days"] or duration_days
        daily_minutes = intent["daily_minutes"] or daily_minutes
    normalized = _normalize_topic(topic)
    existing = learner.repo.list_user_courses(user_id)
    dup = next((c for c in existing if c.get("normalized_topic") == normalized), None)

    # 全部 DB 写在一个事务（失败整体回滚，不留下半创建的课程状态）
    with learner.repo.transaction():
        if dup is not None:
            course_id = dup["course_id"]
        else:
            course_id = resolve_course_id(topic, [c["course_id"] for c in existing])
            learner.repo.upsert_user_course(
                {"user_id": user_id, "course_id": course_id, "display_name": topic,
                 "topic": topic, "normalized_topic": normalized,
                 "duration_days": int(duration_days), "daily_minutes": int(daily_minutes),
                 "created_at": _now_iso(), "updated_at": _now_iso()}
            )
        learner.ensure_course(user_id, course_id)

        # 一个课程一个 active goal（旧 active → completed）
        goal_id = resolve_goal_id(user_id, course_id)
        for g in learner.repo.list_goals(user_id, status="active"):
            if g.get("course_id") == course_id and g["goal_id"] != goal_id:
                learner.set_goal_status(user_id, g["goal_id"], "completed")

        learner.upsert_goal(user_id, goal_id, course_id, name=topic, target=goal or "")
        learner.set_current_goal(user_id, course_id, goal_id)
        learner.record_event({"event_type": "COURSE_CREATED", "user_id": user_id,
                              "course_id": course_id, "payload": {"topic": topic}})

    return get_course(user_id, course_id, learner)


def get_course(user_id: str, course_id: str,
               learner: Optional[LearnerModelService] = None) -> dict:
    """取用户课程：必须先有 user_courses 归属，否则 404/KeyError。"""
    learner = learner or LearnerModelService()
    row = learner.repo.get_user_course(user_id, course_id)
    if row is None:
        raise KeyError(f"course not found: {course_id}")
    return _compose_course(user_id, course_id, row, learner)


def rename_course(user_id: str, course_id: str, new_title: str,
                  learner: Optional[LearnerModelService] = None) -> dict:
    """只改 user_courses.display_name，绝不触碰共享 Built-in Domain title。"""
    learner = learner or LearnerModelService()
    row = learner.repo.get_user_course(user_id, course_id)
    if row is None:
        raise KeyError(f"course not found: {course_id}")
    title = (new_title or "").strip() or row["display_name"]
    with learner.repo.transaction():
        learner.repo.upsert_user_course({**row, "display_name": title, "updated_at": _now_iso()})
        learner.record_event({"event_type": "COURSE_UPDATED", "user_id": user_id,
                              "course_id": course_id, "payload": {"title": title}})
    return get_course(user_id, course_id, learner)


def delete_course(user_id: str, course_id: str,
                  learner: Optional[LearnerModelService] = None) -> None:
    """真正级联删除当前用户的课程数据（单事务，共享 Built-in Domain 不碰）。"""
    learner = learner or LearnerModelService()
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    with learner.repo.transaction():
        learner.repo.delete_user_course_data(user_id, course_id)
        # 审计事件在删除之后写入；delete_user_course_data 不删 events，事件留存
        learner.record_event({"event_type": "COURSE_DELETED", "user_id": user_id,
                              "course_id": course_id, "payload": {}})

    # 课程资料块（user+course 双隔离）也须清除，避免孤儿 chunks 残留
    try:
        from edu_agent.tools import kb_store

        kb_store.delete_course_chunks(user_id, course_id)
    except Exception:  # noqa: BLE001 - 资料清理失败不影响课程已删除
        logger.warning("[course] delete course chunks failed: %s/%s", user_id, course_id, exc_info=True)


def _compose_course(user_id: str, course_id: str, row: dict,
                    learner: LearnerModelService) -> dict:
    state = learner.repo.get_course_state(user_id, course_id) or {}
    # 复用唯一 active goal 解析（current_goal_id 优先 → priority fallback），
    # 与 Chat / Plan 看到同一个 current goal
    active_goal = learner.resolve_active_goal(user_id, course_id)
    goal = None
    if active_goal is not None:
        try:
            target_kcs = list(active_goal.target_kcs or [])
        except Exception:  # noqa: BLE001
            target_kcs = []
        goal = {"goal_id": active_goal.goal_id, "name": active_goal.goal_name,
                "target": active_goal.target, "progress": float(active_goal.progress or 0.0),
                "target_kcs": target_kcs}
    plan = learner.repo.get_plan(user_id, course_id)
    return {
        "course_id": course_id,
        "display_name": row.get("display_name") or row.get("title") or course_id,
        "topic": row.get("topic", ""),
        "goal": goal,
        "progress": float(state.get("progress", 0.0)),
        "plan_summary": (plan or {}).get("summary", ""),
        "duration_days": int(row.get("duration_days") or 14),
        "daily_minutes": int(row.get("daily_minutes") or 60),
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


_NL_RE = re.compile(r"(我想|我要|我准备|学习|学一下|几天|每天|小时|分钟|目标|学会|入门|进阶|周)")


def _looks_like_natural_language(text: str) -> bool:
    """启发式：包含自然语言特征词才走 parse（"Python 数据分析"这种纯标题原样处理）。"""
    return bool(_NL_RE.search(text))


def _parse_minutes(daily_time: str) -> int:
    if not daily_time:
        return 60
    m = re.search(r"(\d+)\s*(小时|h|hour)", daily_time, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(分钟|min)", daily_time, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 60
