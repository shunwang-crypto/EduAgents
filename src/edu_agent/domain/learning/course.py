"""领域课程模型（Course）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from edu_agent.domain.learning.kc_relation import KCRelation
from edu_agent.domain.learning.knowledge_component import KnowledgeComponent


@dataclass
class Course:
    """一门课程的领域知识结构。"""

    course_id: str
    title: str
    components: List[KnowledgeComponent] = field(default_factory=list)
    relations: List[KCRelation] = field(default_factory=list)

    def kc_by_id(self, kc_id: str) -> Optional[KnowledgeComponent]:
        for kc in self.components:
            if kc.kc_id == kc_id:
                return kc
        return None

    def find_kc_by_title(self, title: str) -> Optional[KnowledgeComponent]:
        """按标题（精确/包含）查找 KC，供前端把知识节点标题映射为 kc_id。"""
        if not title:
            return None
        for kc in self.components:
            if kc.title == title or kc.kc_id.lower() == title.strip().lower():
                return kc
        for kc in self.components:
            if title in kc.title or kc.title in title:
                return kc
        return None

    def prerequisites(self, kc_id: str) -> List[str]:
        """kc_id 的直接前置（只算 prerequisite 关系）。"""
        return [
            rel.from_kc
            for rel in self.relations
            if rel.to_kc == kc_id and rel.relation == "prerequisite"
        ]

    def dependents(self, kc_id: str) -> List[str]:
        """依赖 kc_id 的节点（被它作为前置）。"""
        return [
            rel.to_kc
            for rel in self.relations
            if rel.from_kc == kc_id and rel.relation == "prerequisite"
        ]

    def all_prerequisites_transitive(self, kc_id: str) -> List[str]:
        """kc_id 的所有传递前置（含间接）。"""
        result: List[str] = []
        stack = list(self.prerequisites(kc_id))
        seen: set = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            stack.extend(self.prerequisites(current))
        return result
