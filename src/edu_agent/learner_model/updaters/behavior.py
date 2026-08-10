"""Behavior Updater：从 Events 真实聚合 30 天行为。

- activity_count_30d：严格按 UTC 时间过滤最近 30 天。
- average_session_minutes：由 SESSION_STARTED/SESSION_ENDED 配对计算；
  无 session 数据返回 None（不编造 25）。
- streak_days：基于事件 UTC 日期。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import BehaviorState

_EVENT_WINDOW_DAYS = 30


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _safe_payload(ev: dict) -> dict:
    import json

    try:
        payload = json.loads(ev.get("payload_json") or "{}")
        return payload if isinstance(payload, dict) else {}
    except (ValueError, TypeError):
        return {}


def aggregate(
    repo: LearnerRepository, user_id: str, course_id: str
) -> BehaviorState:
    """聚合该课程最近 30 天行为 → BehaviorState。"""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=_EVENT_WINDOW_DAYS)).isoformat()
    events = repo.list_events_since(user_id, course_id, since, limit=1000)

    activity_count = len(events)
    topic_counter: Counter = Counter()
    sessions: Dict[str, float] = {}
    session_end: Dict[str, float] = {}
    for ev in events:
        payload = _safe_payload(ev)
        topic = payload.get("topic") or payload.get("kc_name") or ev.get("kc_id") or ""
        if topic:
            topic_counter[topic] += 1
        sid = ev.get("session_id") or ""
        ts = _parse_ts(ev.get("timestamp") or "")
        if not ts:
            continue
        ts_seconds = ts.timestamp()
        if ev.get("event_type") == "SESSION_STARTED" and sid:
            sessions.setdefault(sid, ts_seconds)
        elif ev.get("event_type") == "SESSION_ENDED" and sid:
            session_end[sid] = ts_seconds

    average_session_minutes = None
    durations = [
        end - sessions[sid]
        for sid, end in session_end.items()
        if sid in sessions and end > sessions[sid]
    ]
    if durations:
        average_session_minutes = round(
            sum(durations) / len(durations) / 60.0, 1
        )

    return BehaviorState(
        activity_count_30d=activity_count,
        streak_days=_estimate_streak(events),
        average_session_minutes=average_session_minutes,
        recent_topics=[t for t, _ in topic_counter.most_common(5)],
        frequent_revisited_topics=[t for t, c in topic_counter.most_common(5) if c >= 3],
    )


def _estimate_streak(events: List[dict]) -> int:
    """按事件 UTC 日期估计连续天数。"""
    seen: set = set()
    for ev in events:
        parsed = _parse_ts(ev.get("timestamp") or "")
        if parsed:
            seen.add(parsed.date().isoformat())
    if not seen:
        return 0
    streak = 0
    cur = date.today()
    while cur.isoformat() in seen:
        streak += 1
        cur = date.fromordinal(cur.toordinal() - 1)
    return streak
