"""Semantic Evidence Classifier：自由文本 → Evidence Candidates。

职责：
- 只产出 Evidence Candidate（结构化），绝不直接改画像数值。
- LLM 可选（LEARNER_MODEL_SEMANTIC_INFERENCE_ENABLED）；无模型时用高确定规则。
- 高确定规则（避免把普通「为什么」误判成 misconception）：
  * 只有「我一直以为 X 是 Y」「我总是搞混 X 和 Y」「原来 X 不是 Y 啊」等明确自述
    才创建 misconception candidate。
  * 学生用自己的话解释概念（CHECK_UNDERSTANDING_RESPONSE / SELF_EXPLANATION_SUBMITTED）
    → 正能力证据（understanding/reasoning/expression），medium。
"""

from __future__ import annotations

from typing import Any, Dict, List

from edu_agent.learner_model.evidence.schemas import LearningEvent, StructuredEvidence

# 高确定误解关键词（明确自述混淆，而非提问）
_MISCONCEPTION_PATTERNS = [
    "我一直以为",
    "总是搞混",
    "一直混淆",
    "总把",
    "当成",
    "以为",
    "原来不是",
    "搞错了",
    "之前理解错了",
]

# 混淆类型 → misconception_key 的推断（可扩展）
_MISCONCEPTION_KEYS = {
    "静态": "static_vs_dynamic_type",
    "动态类型": "static_vs_dynamic_type",
    "父类": "reference_vs_object",
    "引用": "reference_vs_object",
    "重载": "overload_vs_override",
    "重写": "overload_vs_override",
    "运行时": "reference_vs_object",
}


def _default_key_for(kc_id: str, text: str) -> str:
    for kw, key in _MISCONCEPTION_KEYS.items():
        if kw in text:
            return key
    return f"{kc_id}_confusion"


def _is_self_confession(text: str) -> bool:
    """高确定自述混淆（不以「为什么」等提问开头）。"""
    stripped = text.strip()
    if not stripped or stripped.startswith(("为什么", "为何", "怎么", "如何")):
        return False
    return any(p in text for p in _MISCONCEPTION_PATTERNS)


def classify(event: LearningEvent, use_llm: bool = False) -> List[StructuredEvidence]:
    """自由文本 + KC → Evidence Candidates（只出候选，落库由 Updater 决定）。"""
    text = " ".join(
        str(v) for v in (event.payload or {}).values() if isinstance(v, str)
    )
    kc = event.kc_id
    if not kc or not text:
        return []

    candidates: List[StructuredEvidence] = []
    t = event.event_type

    # 1) 理解检查 / 自述解释 → 正能力证据（medium，需分类器 confidence）
    if t in ("CHECK_UNDERSTANDING_RESPONSE", "SELF_EXPLANATION_SUBMITTED", "CONCEPT_COMPARISON_RESPONSE"):
        ability_hits: List[str] = []
        if _looks_explanatory(text):
            ability_hits = ["understanding", "reasoning"]
            if len(text) > 60:
                ability_hits.append("expression")
        for ability in ability_hits:
            candidates.append(
                StructuredEvidence.from_event(
                    event,
                    entity_type="ability",
                    entity_key=ability,
                    direction="pos",
                    meaningful=True,
                    extra_payload={"classifier_version": "semantic-v1", "classifier_confidence": 0.6},
                )
            )

    # 2) 误解候选：只接受高确定自述（不把普通提问当误解）
    if t in ("SELF_REPORTED_CONFUSION", "RE_EXPLAIN_REQUESTED", "CHECK_UNDERSTANDING_RESPONSE"):
        if _is_self_confession(text):
            key = _default_key_for(kc, text)
            candidates.append(
                StructuredEvidence.from_event(
                    event,
                    entity_type="misconception",
                    entity_key=kc,
                    direction="pos",
                    meaningful=True,
                    extra_payload={
                        "misconception_key": key,
                        "description_hint": text[:120],
                        "classifier_version": "semantic-v1",
                        "classifier_confidence": 0.7,
                    },
                )
            )

    # 3) 正确解释（能讲清楚机制）→ 误解弱化信号
    if t in ("CHECK_UNDERSTANDING_RESPONSE", "SELF_EXPLANATION_SUBMITTED") and _looks_explanatory(text):
        candidates.append(
            StructuredEvidence.from_event(
                event,
                entity_type="misconception",
                entity_key=kc,
                direction="neg",
                meaningful=True,
                extra_payload={
                    "misconception_key": _default_key_for(kc, text),
                    "classifier_version": "semantic-v1",
                    "classifier_confidence": 0.55,
                },
            )
        )

    if use_llm:
        candidates += _llm_candidates(event)

    return candidates


def _looks_explanatory(text: str) -> bool:
    """判断文本是否像「用自己的话解释」而非简单确认。"""
    markers = ["因为", "所以", "本质", "在于", "决定", "机制", "编译", "运行", "也就是说", "取决于", "对象", "类型"]
    return len(text.strip()) >= 20 and any(m in text for m in markers)


def _llm_candidates(event: LearningEvent) -> List[StructuredEvidence]:
    """（可选）LLM 扩展：V1 保持与高确定规则一致的保守输出，避免误判。

    真实接入模型时在此调用，且只返回 Evidence Candidate。
    """
    return []
