"""领域知识组件（KnowledgeComponent / KC）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class KnowledgeComponent:
    """知识组件（KC）。"""

    kc_id: str
    title: str
    category: str = "core"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    difficulty: str = "medium"  # easy / medium / hard
