"""LearningEvent 与 StructuredEvidence 模型。

- LearningEvent：描述「发生过什么」，append-only，不修改。
- StructuredEvidence：从事件提取的、可被 Updater 消费的结构化证据。
  事件本身是历史；证据是「当前画像应如何调整」的输入。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

EvidenceStrength = Literal["weak", "medium", "strong"]
SourceReliability = Literal[
    "USER_EXPLICIT",
    "TEACHING_INTERACTION",
    "BEHAVIOR_INFERENCE",
    "LLM_INFERENCE",
    "SYSTEM_OBSERVATION",
    "EXTERNAL_ASSESSMENT",
]

# 可靠度数值（用户明确声明 > 可靠正式数据 > 重复行为 > LLM 推断 > 单次行为）
SOURCE_RELIABILITY_SCORE: Dict[SourceReliability, float] = {
    "USER_EXPLICIT": 1.0,
    "EXTERNAL_ASSESSMENT": 0.95,
    "TEACHING_INTERACTION": 0.7,
    "SYSTEM_OBSERVATION": 0.6,
    "BEHAVIOR_INFERENCE": 0.4,
    "LLM_INFERENCE": 0.3,
}

STRENGTH_WEIGHT: Dict[EvidenceStrength, float] = {"weak": 0.1, "medium": 0.3, "strong": 0.6}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LearningEvent(BaseModel):
    """一条真实用户行为（append-only）。"""

    event_id: str = Field(default="")
    schema_version: int = Field(default=1)
    event_type: str = Field(description="事件类型，见 EVENT_TYPES")
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    kc_id: str = Field(default="")
    session_id: str = Field(default="")
    timestamp: str = Field(default="")
    source: SourceReliability = Field(default="SYSTEM_OBSERVATION")
    evidence_strength: EvidenceStrength = Field(default="weak")
    payload: Dict[str, Any] = Field(default_factory=dict)


class StructuredEvidence(BaseModel):
    """从事件提取的结构化证据，供特定 Updater 消费。

    entity_type：knowledge / preference / misconception / profile_fact / goal /
                 ability / behavior / semantic_memory
    direction：pos=正向(强化/提高) neg=负向(弱化/降低) neutral=中性(仅曝光)
    weight：0-1 综合强度（strength × source_reliability）
    """

    evidence_id: str = Field(default="")
    event_id: str = Field(default="")
    event_type: str = Field(default="")
    timestamp: str = Field(default="")
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    kc_id: str = Field(default="")
    entity_type: str = Field(default="knowledge")
    entity_key: str = Field(default="", description="如 kc_id / preference_key / fact_key")
    direction: Literal["pos", "neg", "neutral"] = Field(default="neutral")
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    source: SourceReliability = Field(default="SYSTEM_OBSERVATION")
    meaningful_for_profile: bool = Field(default=False)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_event(
        cls,
        event: LearningEvent,
        entity_type: str,
        entity_key: str,
        direction: Literal["pos", "neg", "neutral"],
        meaningful: bool,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> "StructuredEvidence":
        weight = STRENGTH_WEIGHT.get(event.evidence_strength, 0.1) * SOURCE_RELIABILITY_SCORE.get(
            event.source, 0.5
        )
        payload = dict(event.payload)
        if extra_payload:
            payload.update(extra_payload)
        return cls(
            evidence_id=f"EV-{event.event_id}-{entity_type}-{entity_key}",
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp or _now_iso(),
            user_id=event.user_id,
            course_id=event.course_id,
            goal_id=event.goal_id,
            kc_id=event.kc_id,
            entity_type=entity_type,
            entity_key=entity_key,
            direction=direction,
            weight=weight,
            source=event.source,
            meaningful_for_profile=meaningful,
            payload=payload,
        )
