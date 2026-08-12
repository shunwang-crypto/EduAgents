"""CourseCategoryService：课程分类（纯组织层，user scoped）。

Category 唯一职责：把用户自己创建的 Course 分组整理。
Category 不拥有 mastery / KC / goal / learner state / semantic memory /
study plan / progress / RAG / sources / conversation / evidence 中的任何一项；
所有 Adaptive 数据继续严格绑定 user_id + course_id。

只做普通 CRUD：
- list_categories / create_category / rename_category / delete_category / assign_course
不造 Domain Aggregate / Agent / Workflow / Resolver。

删除分类的正式语义（由本 Service 保证，原子）：
    DELETE Category → 该分类下 Course.category_id = NULL → Course 本身绝不删除
    （Goal / KC / Mastery / Memory / Plan / Sources / Conversations / Lessons / Progress 全部不变）
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import List, Optional

from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def list_categories(
    user_id: str, learner: Optional[LearnerModelService] = None
) -> List[dict]:
    """列出当前用户的全部分类（user scoped；USER-B 看不到 USER-A 的分类）。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    return learner.repo.list_course_categories(user_id)


def create_category(
    user_id: str, name: str, learner: Optional[LearnerModelService] = None
) -> dict:
    """新建分类：稳定随机 ID（CAT-<uuid>，每个 user 拥有自己的分类，不做全局固定 ID）。"""
    learner = learner or LearnerModelService()
    learner.ensure_learner(user_id)
    name = _normalize_name(name)
    if not name:
        raise ValueError("分类名称不能为空")
    if len(name) > 60:
        raise ValueError("分类名称过长")
    existing = learner.repo.list_course_categories(user_id)
    if any(c.get("name", "").strip().lower() == name.lower() for c in existing):
        raise ValueError(f"分类「{name}」已存在")
    category_id = f"CAT-{uuid.uuid4().hex[:12]}"
    try:
        with learner.repo.transaction():
            learner.repo.create_course_category(user_id, category_id, name)
            learner.record_event({"event_type": "CATEGORY_CREATED", "user_id": user_id,
                                  "course_id": "", "payload": {"category_id": category_id, "name": name}})
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"分类「{name}」已存在") from exc
    return learner.repo.get_course_category(user_id, category_id) or {
        "category_id": category_id, "user_id": user_id, "name": name}


def rename_category(
    user_id: str, category_id: str, name: str,
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """重命名分类：只改 course_categories.name，不触碰任何 Course Learner State。"""
    learner = learner or LearnerModelService()
    row = learner.repo.get_course_category(user_id, category_id)
    if row is None:
        raise KeyError(f"category not found: {category_id}")
    name = _normalize_name(name)
    if not name:
        raise ValueError("分类名称不能为空")
    if len(name) > 60:
        raise ValueError("分类名称过长")
    existing = learner.repo.list_course_categories(user_id)
    if any(c["category_id"] != category_id and c.get("name", "").strip().lower() == name.lower()
           for c in existing):
        raise ValueError(f"分类「{name}」已存在")
    with learner.repo.transaction():
        learner.repo.rename_course_category(user_id, category_id, name)
        learner.record_event({"event_type": "CATEGORY_UPDATED", "user_id": user_id,
                              "course_id": "", "payload": {"category_id": category_id, "name": name}})
    return learner.repo.get_course_category(user_id, category_id) or row


def delete_category(
    user_id: str, category_id: str, learner: Optional[LearnerModelService] = None
) -> None:
    """删除分类（原子）：分类下课程移到未分类（category_id=NULL），课程本身绝不删除。

    不删除 Course / Plan / Chat / Sources / Learner State。
    """
    learner = learner or LearnerModelService()
    if learner.repo.get_course_category(user_id, category_id) is None:
        raise KeyError(f"category not found: {category_id}")
    with learner.repo.transaction():
        learner.repo.delete_course_category(user_id, category_id)
        learner.record_event({"event_type": "CATEGORY_DELETED", "user_id": user_id,
                              "course_id": "", "payload": {"category_id": category_id}})


def assign_course(
    user_id: str, course_id: str, category_id: Optional[str],
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """把课程归入分类；category_id=None = 移到未分类。Category 必须是当前用户的。"""
    learner = learner or LearnerModelService()
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    if category_id is not None and learner.repo.get_course_category(user_id, category_id) is None:
        raise KeyError(f"category not found: {category_id}")
    with learner.repo.transaction():
        learner.repo.set_course_category(user_id, course_id, category_id)
        learner.record_event({"event_type": "COURSE_CATEGORY_ASSIGNED", "user_id": user_id,
                              "course_id": course_id,
                              "payload": {"category_id": category_id}})
    from edu_agent.application.course_service import get_course

    return get_course(user_id, course_id, learner)
