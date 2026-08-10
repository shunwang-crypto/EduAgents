"""EvidenceExtractor：LearningEvent → StructuredEvidence（规则）+ Semantic Classifier（语义候选）。

- 规则证据：确定、低误判（曝光/偏好/事实/目标）。
- 语义候选：只对高信息量事件调用 semantic_classifier，产出能力/误解候选。
- 产出的是 Evidence Candidate；是否落库由 Updater 决定。
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from edu_agent.learner_model.evidence.rules import event_meta, rules_for
from edu_agent.learner_model.evidence.schemas import (
    LearningEvent,
    StructuredEvidence,
)

# 语义分类器处理的高信息量事件（避免对每个事件都做语义推断）
_HIGH_INFO_EVENTS = {
    "CHECK_UNDERSTANDING_RESPONSE",
    "SELF_EXPLANATION_SUBMITTED",
    "CONCEPT_COMPARISON_RESPONSE",
    "SELF_REPORTED_CONFUSION",
    "RE_EXPLAIN_REQUESTED",
    "FEEDBACK_GIVEN",
}


def build_event(
    event_type: str,
    user_id: str,
    course_id: str = "",
    kc_id: str = "",
    goal_id: str = "",
    session_id: str = "",
    payload: Optional[dict] = None,
    event_id: str = "",
) -> LearningEvent:
    """构造 LearningEvent（自动填强度/来源/时间戳）。"""
    from datetime import datetime, timezone

    strength, source, _ = event_meta(event_type)
    return LearningEvent(
        event_id=event_id or f"EV-{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        user_id=user_id,
        course_id=course_id,
        kc_id=kc_id,
        goal_id=goal_id,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        evidence_strength=strength,
        payload=payload or {},
    )


def extract_evidence(event: LearningEvent, use_semantic: bool = False) -> List[StructuredEvidence]:
    """提取证据 = 规则证据 + （高信息量事件的）语义候选。

    - 教学理解检查类事件（CHECK_UNDERSTANDING_RESPONSE 等）**总是**跑高确定规则
      语义分类（不依赖 LLM，也不依赖开关），否则 Ability/Misconception 永远没有证据来源。
    - use_semantic 控制的是额外 LLM 语义推断。
    """
    evidences: List[StructuredEvidence] = []
    for entity_type, direction, entity_key, meaningful in rules_for(event):
        if not entity_key:
            continue
        evidences.append(
            StructuredEvidence.from_event(
                event,
                entity_type=entity_type,
                entity_key=entity_key,
                direction=direction,
                meaningful=meaningful,
            )
        )

    # 高信息量事件总是跑规则版语义分类（Ability/Misconception 的证据来源）
    if event.event_type in _HIGH_INFO_EVENTS:
        from edu_agent.learner_model.evidence.semantic_classifier import classify

        evidences += classify(event, use_llm=False)

    if use_semantic and event.event_type in _HIGH_INFO_EVENTS:
        from edu_agent.learner_model.evidence.semantic_classifier import classify

        evidences += classify(event, use_llm=True)

    return evidences
