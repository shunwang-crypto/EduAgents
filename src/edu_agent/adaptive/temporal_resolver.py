"""TemporalResolver：处理「掌握度不是永久不变」。

- mastery=None（UNKNOWN）→ effective_state=unknown，raw_mastery=None，不判 mastered/weak。
- 只有 mastery 有真实值才判断 weak/learning/mastered/needs_refresh。
- recency_days 由 last_evidence_at 计算（无证据 → None）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from edu_agent.adaptive.schemas import TemporalState
from edu_agent.learner_model.schemas import KnowledgeItem


def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_days(last_evidence_at: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    parsed = _parse_iso(last_evidence_at)
    if parsed is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    delta = now - parsed
    return max(0.0, delta.total_seconds() / 86400.0)


def resolve(
    knowledge: Optional[KnowledgeItem],
    now: Optional[datetime] = None,
) -> TemporalState:
    """把单个 KC 的掌握状态换算成带时间衰减的有效状态。"""
    if knowledge is None or knowledge.mastery is None:
        return TemporalState(
            raw_mastery=None, recency_days=None, review_risk="low", effective_state="unknown"
        )

    mastery = knowledge.mastery
    recency = _recency_days(knowledge.last_evidence_at, now)

    if recency is None:
        # 无时间信息 → 保守：按 mastery 判断但不判高复习风险
        if mastery >= 0.7:
            return TemporalState(raw_mastery=mastery, recency_days=None,
                                 review_risk="low", effective_state="mastered")
        if mastery >= 0.3:
            return TemporalState(raw_mastery=mastery, recency_days=None,
                                 review_risk="low", effective_state="learning")
        return TemporalState(raw_mastery=mastery, recency_days=None,
                             review_risk="low", effective_state="weak")

    if mastery >= 0.7:
        if recency > 90:
            return TemporalState(raw_mastery=mastery, recency_days=recency,
                                 review_risk="high", effective_state="needs_refresh")
        if recency > 30:
            return TemporalState(raw_mastery=mastery, recency_days=recency,
                                 review_risk="medium", effective_state="needs_refresh")
        return TemporalState(raw_mastery=mastery, recency_days=recency,
                             review_risk="low", effective_state="mastered")

    if mastery >= 0.3:
        return TemporalState(raw_mastery=mastery, recency_days=recency,
                             review_risk="low", effective_state="learning")

    return TemporalState(raw_mastery=mastery, recency_days=recency,
                         review_risk="low", effective_state="weak")


def recency_days(last_evidence_at: Optional[str]) -> Optional[float]:
    """供外部复用的 recency 计算（无时间信息返回 None）。"""
    return _recency_days(last_evidence_at)


def review_risk_score(state: TemporalState) -> float:
    """复习风险数值化（供排序/展示）：low=0 / medium=0.5 / high=1.0。"""
    return {"low": 0.0, "medium": 0.5, "high": 1.0}.get(state.review_risk, 0.0)
