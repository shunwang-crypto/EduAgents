"""轻量证据模型（替代已删除的完整 evidence 包）。

范围收缩后只保留 updaters 需要的字段，无 provenance/幂等/落库（events 表已是审计）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class LightEvidence:
    user_id: str = ""
    course_id: str = ""
    entity_type: str = "knowledge"
    entity_key: str = ""
    direction: str = "neutral"  # pos / neg / neutral
    event_type: str = ""
    source: str = "SYSTEM_OBSERVATION"
    payload: Dict[str, Any] = field(default_factory=dict)
    weight: float = 0.1
