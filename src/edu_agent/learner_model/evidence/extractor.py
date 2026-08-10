"""EvidenceExtractor：LearningEvent → List[StructuredEvidence]。

规则为主（rules.py），复杂语义判断可挂 LLM（可选，默认关闭）。
LLM 只输出 Evidence Candidate；是否落库由 Updater 决定，禁止 LLM 直接改画像。
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from edu_agent.learner_model.evidence.rules import event_meta, rules_for
from edu_agent.learner_model.evidence.schemas import (
    LearningEvent,
    StructuredEvidence,
)


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


def extract_evidence(event: LearningEvent) -> List[StructuredEvidence]:
    """把事件转成结构化证据列表（可能为空）。"""
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
    return evidences


def llm_inference_hint(
    event: LearningEvent,
    use_llm: bool = False,
) -> List[StructuredEvidence]:
    """（可选）LLM 语义推断：从自由文本抽取 misconception / preference 候选。

    默认关闭（use_llm=False 返回空）。开启时返回的仍是「Evidence Candidate」，
    由 Updater 按置信度规则决定是否落库，不直接改画像。
    """
    if not use_llm:
        return []
    return _llm_rule_inference(event)


def _llm_rule_inference(event: LearningEvent) -> List[StructuredEvidence]:
    """V1 用规则近似 LLM 推断（避免每次调模型）：识别误解关键词。"""
    text = " ".join(
        str(v) for v in (event.payload or {}).values() if isinstance(v, str)
    )
    kc = event.kc_id
    if not kc or not text:
        return []
    confusion_kw = ["不明白", "为什么", "搞不懂", "混乱", "区别", "混淆", "没懂"]
    if any(kw in text for kw in confusion_kw):
        return [
            StructuredEvidence.from_event(
                event,
                entity_type="misconception",
                entity_key=kc,
                direction="pos",
                meaningful=True,
                extra_payload={"description_hint": text[:120]},
            )
        ]
    return []
