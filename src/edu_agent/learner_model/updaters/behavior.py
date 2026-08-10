"""Behavior Updater：从 Events 实时聚合近期行为快照。

不单独落库（行为是聚合结果）；service.build_bundle 时调用 aggregate()。
未来可扩展为按天写入行为聚合表。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import BehaviorState

_EVENT_WINDOW_DAYS = 30


def aggregate(
    repo: LearnerRepository, user_id: str, course_id: str
) -> BehaviorState:
    """聚合该课程近 30 天行为 → BehaviorState。"""
    events = repo.list_events(user_id, course_id, limit=200)
    activity_count = len(events)
    topic_counter: Counter = Counter()
    for ev in events:
        payload = _safe_payload(ev)
        topic = payload.get("topic") or payload.get("kc_name") or ev.get("kc_id") or ""
        if topic:
            topic_counter[topic] += 1

    return BehaviorState(
        activity_count_30d=activity_count,
        streak_days=_estimate_streak(events),
        average_session_minutes=25.0,  # 原型默认；未来按 SESSION 事件计算
        recent_topics=[t for t, _ in topic_counter.most_common(5)],
        frequent_revisited_topics=[
            t for t, c in topic_counter.most_common(5) if c >= 3
        ],
    )


def _safe_payload(ev: dict) -> dict:
    import json

    try:
        payload = json.loads(ev.get("payload_json") or "{}")
        return payload if isinstance(payload, dict) else {}
    except (ValueError, TypeError):
        return {}


def _estimate_streak(events: List[dict]) -> int:
    """按事件日期估计连续天数（简单规则，原型够用）。"""
    seen: set = set()
    for ev in events:
        ts = ev.get("timestamp") or ""
        if len(ts) >= 10:
            seen.add(ts[:10])
    if not seen:
        return 0
    streak = 0
    from datetime import date, datetime

    cur = date.today()
    while cur.isoformat() in seen:
        streak += 1
        cur = date.fromordinal(cur.toordinal() - 1)
    return streak
