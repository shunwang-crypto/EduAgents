"""领域知识关系（KCRelation）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KCRelation:
    """KC 之间的关系。"""

    from_kc: str
    to_kc: str
    relation: str = "prerequisite"  # prerequisite / related / part_of / transfer
    weight: float = 1.0
