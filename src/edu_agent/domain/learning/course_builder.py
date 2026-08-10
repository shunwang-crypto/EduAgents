"""Course Builder：KnowledgeMap / 学习计划节点 → 领域 Course（KC + 关系）。

- KnowledgeNode.id 直接作为 course-local kc_id（统一，不再到处 find_kc_by_title）。
- 关系：从节点 prerequisites（字符串列表）映射到同课程 KC id。
- 生成后 register_course + 持久化到 SQLite（domain_courses/domain_kcs/domain_kc_relations），
  应用重启不丢失。
"""

from __future__ import annotations

from typing import List, Optional

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_relation import KCRelation
from edu_agent.domain.learning.knowledge_component import KnowledgeComponent
from edu_agent.learner_model.repository import LearnerRepository


def build_course_from_nodes(
    course_id: str,
    title: str,
    nodes: List[dict],
    topic: str = "",
) -> Course:
    """从学习计划节点列表构建 Course。

    nodes: [{"id": ..., "title": ..., "category": ..., "summary": ...,
             "prerequisites": [...], "difficulty": ...}]
    """
    components: List[KnowledgeComponent] = []
    for node in nodes:
        components.append(
            KnowledgeComponent(
                kc_id=node.get("id") or node.get("title") or "",
                title=node.get("title") or node.get("id") or "",
                category=node.get("category") or "core",
                description=node.get("summary", ""),
                difficulty=node.get("difficulty", "medium"),
            )
        )
    # 前置关系：prerequisites 中的字符串 → 匹配到本课程节点 id（id/title）
    id_to_title = {c.kc_id: c.title for c in components if c.kc_id}
    title_to_id = {v: k for k, v in id_to_title.items()}
    relations: List[KCRelation] = []
    for node in nodes:
        kc_id = node.get("id") or node.get("title") or ""
        for prereq in node.get("prerequisites") or []:
            target = prereq
            if target in title_to_id:  # 前置写的是节点标题 → 映射为 kc_id
                target = title_to_id[target]
            elif target in id_to_title:  # 前置直接是 kc_id
                pass
            elif target in id_to_title.values():  # 容错：title 匹配
                target = title_to_id.get(target) or target
            if target and target != kc_id:
                relations.append(KCRelation(target, kc_id, "prerequisite", 1.0))
    return Course(course_id=course_id, title=title, components=components, relations=relations)


def persist_course(repo: LearnerRepository, course: Course, topic: str = "") -> None:
    """持久化自定义课程 Domain Model 到 SQLite。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    existing = repo.get_domain_course(course.course_id)
    if existing is None:
        repo.upsert_domain_course(
            {"course_id": course.course_id, "title": course.title, "topic": topic, "created_at": now}
        )
    for kc in course.components:
        repo.upsert_domain_kc(
            {
                "course_id": course.course_id,
                "kc_id": kc.kc_id,
                "title": kc.title,
                "category": kc.category,
                "description": kc.description,
                "difficulty": kc.difficulty,
            }
        )
    for rel in course.relations:
        repo.upsert_domain_relation(
            {
                "course_id": course.course_id,
                "from_kc": rel.from_kc,
                "to_kc": rel.to_kc,
                "relation": rel.relation,
                "weight": rel.weight,
            }
        )


def load_course_from_repo(repo: LearnerRepository, course_id: str) -> Optional[Course]:
    """从 SQLite 恢复自定义课程（应用重启后仍可用）。"""
    row = repo.get_domain_course(course_id)
    if row is None:
        return None
    kcs = repo.list_domain_kcs(course_id)
    rels = repo.list_domain_relations(course_id)
    return Course(
        course_id=course_id,
        title=row.get("title", course_id),
        components=[
            KnowledgeComponent(
                kc_id=k["kc_id"], title=k.get("title", k["kc_id"]),
                category=k.get("category", "core"),
                description=k.get("description", ""),
                difficulty=k.get("difficulty", "medium"),
            )
            for k in kcs
        ],
        relations=[
            KCRelation(r["from_kc"], r["to_kc"], r.get("relation", "prerequisite"), r.get("weight", 1.0))
            for r in rels
        ],
    )
