"""动态 KCGraph 持久化 + 加载优先级服务。

这是 Study Plan / Learning Map / Tutor / Adaptive Planner / Learner Model
共用的 *canonical* 知识图来源。

加载优先级（graph source）：
1. 当前 ``(user_id, course_id)`` 的动态 persisted KCGraph（graph_source=generated）；
2. 内置 ``get_course(course_id)``（built-in：LLM-RAG / JAVA-OOP 等）；
3. 两者都无 → 返回 None（调用方应返回明确“无图/需生成”状态）。

持久化采用 additive schema（``course_kc_graph`` 表），与 study_plan 写入
放在同一事务中，保证 Plan 与 Graph 版本一致。重新生成时不会删除 learner
history（learner_kc_states 完全独立，按 canonical kc_id 保留）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_graph import get_course
from edu_agent.learner_model.repository import LearnerRepository

logger = logging.getLogger(__name__)

_LEGACY_TEMP_RE = re.compile(r"^knowledge-\d+$", re.IGNORECASE)


@dataclass
class ActiveGraph:
    course: Course
    graph_source: str  # generated / builtin / legacy
    graph_version: int


def _course_to_rows(course: Course) -> Tuple[List[list], List[list]]:
    nodes = [
        [c.kc_id, c.title, c.category, c.description, c.difficulty, c.tags]
        for c in course.components
    ]
    edges = [[r.from_kc, r.to_kc, r.relation] for r in course.relations]
    return nodes, edges


def _rows_to_course(
    course_id: str, display_name: str, goal: str,
    nodes: List[list], edges: List[list],
) -> Course:
    from edu_agent.domain.learning.kc_relation import KCRelation
    from edu_agent.domain.learning.knowledge_component import KnowledgeComponent

    components = [
        KnowledgeComponent(
            kc_id=n[0],
            title=n[1],
            category=n[2] if len(n) > 2 else "core",
            description=n[3] if len(n) > 3 else "",
            difficulty=n[4] if len(n) > 4 else "medium",
            tags=n[5] if len(n) > 5 else [],
        )
        for n in nodes
    ]
    relations = [
        KCRelation(
            from_kc=e[0],
            to_kc=e[1],
            relation=e[2] if len(e) > 2 else "prerequisite",
        )
        for e in edges
    ]
    course = Course(
        course_id=course_id,
        title=display_name,
        components=components,
        relations=relations,
        goal=goal,
    )
    return course


class CourseGraphService:
    def __init__(self, repository: LearnerRepository) -> None:
        self.repo = repository

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save_dynamic_graph(
        self,
        user_id: str,
        course_id: str,
        course: Course,
        graph_version: int = 1,
        generated_at: str = "",
        updated_at: str = "",
    ) -> None:
        """持久化动态 canonical KCGraph（应在 study_plan 同一事务内调用）。"""
        import datetime

        now = generated_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated = updated_at or now
        nodes, edges = _course_to_rows(course)
        self.repo.upsert_course_kc_graph(
            {
                "user_id": user_id,
                "course_id": course_id,
                "graph_source": "generated",
                "graph_version": graph_version,
                "generated_at": now,
                "updated_at": updated,
                "nodes_json": json.dumps(nodes, ensure_ascii=False),
                "edges_json": json.dumps(edges, ensure_ascii=False),
            }
        )
        logger.info(
            "dynamic graph persisted",
            extra={
                "user_id": user_id,
                "course_id": course_id,
                "graph_source": "generated",
                "graph_version": graph_version,
                "generated_node_count": len(nodes),
                "generated_edge_count": len(edges),
            },
        )

    # ------------------------------------------------------------------
    # 加载（优先级）
    # ------------------------------------------------------------------
    def load_active_graph(
        self, user_id: str, course_id: str, display_name: str = "", goal: str = ""
    ) -> Optional[ActiveGraph]:
        """按优先级加载 active graph：

        1. 动态 persisted graph（generated）；
        2. 内置 course（builtin）；
        3. 无 → None。
        """
        row = self.repo.get_course_kc_graph(user_id, course_id)
        if row is not None:
            try:
                nodes = json.loads(row["nodes_json"] or "[]")
                edges = json.loads(row["edges_json"] or "[]")
                course = _rows_to_course(
                    course_id, display_name or course_id, goal, nodes, edges
                )
                return ActiveGraph(
                    course=course,
                    graph_source=row.get("graph_source") or "generated",
                    graph_version=row.get("graph_version") or 1,
                )
            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                logger.warning(
                    "corrupt dynamic graph row, falling back to built-in: %s", exc
                )

        try:
            builtin = get_course(course_id)
        except KeyError:
            builtin = None
        if builtin is not None:
            return ActiveGraph(course=builtin, graph_source="builtin", graph_version=0)
        return None

    def has_dynamic_graph(self, user_id: str, course_id: str) -> bool:
        return self.repo.get_course_kc_graph(user_id, course_id) is not None

    @staticmethod
    def is_legacy_temp_id(kc_id: str) -> bool:
        return bool(_LEGACY_TEMP_RE.match(kc_id or ""))
