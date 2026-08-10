"""Learning Event 体系：EduAgents 把学习行为 Evidence 发回合作伙伴 Learner Model。

- EduAgents 只 Emit Evidence，不直接改长期画像数值。
- 事件先写 Outbox（本地 JSON，幂等 event_id），后台异步投递，失败重试。
- 合作伙伴 API 不可用不能阻塞用户主请求。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from edu_agent.tools import app_state_store

EvidenceStrength = Literal["weak", "medium", "strong"]

# ---------------------------------------------------------------------------
# Event 类型（V1）
# ---------------------------------------------------------------------------

SESSION_STARTED = "SESSION_STARTED"
SESSION_ENDED = "SESSION_ENDED"
COURSE_OPENED = "COURSE_OPENED"
TOPIC_STARTED = "TOPIC_STARTED"
TOPIC_COMPLETED = "TOPIC_COMPLETED"
QUESTION_ASKED = "QUESTION_ASKED"
EDUCATIONAL_QUESTION_ASKED = "EDUCATIONAL_QUESTION_ASKED"
EXPLANATION_REQUESTED = "EXPLANATION_REQUESTED"
EXPLANATION_DELIVERED = "EXPLANATION_DELIVERED"
RE_EXPLAIN_REQUESTED = "RE_EXPLAIN_REQUESTED"
EXAMPLE_REQUESTED = "EXAMPLE_REQUESTED"
ANALOGY_REQUESTED = "ANALOGY_REQUESTED"
SIMPLIFICATION_REQUESTED = "SIMPLIFICATION_REQUESTED"
DEEPER_EXPLANATION_REQUESTED = "DEEPER_EXPLANATION_REQUESTED"
PREREQUISITE_REVIEWED = "PREREQUISITE_REVIEWED"
RESOURCE_OPENED = "RESOURCE_OPENED"
RESOURCE_COMPLETED = "RESOURCE_COMPLETED"
PLAN_CREATED = "PLAN_CREATED"
PLAN_UPDATED = "PLAN_UPDATED"
PLAN_STEP_STARTED = "PLAN_STEP_STARTED"
PLAN_STEP_COMPLETED = "PLAN_STEP_COMPLETED"
SELF_REPORTED_UNDERSTANDING = "SELF_REPORTED_UNDERSTANDING"
SELF_REPORTED_CONFUSION = "SELF_REPORTED_CONFUSION"
TEACHING_MODE_SWITCHED = "TEACHING_MODE_SWITCHED"
FEEDBACK_GIVEN = "FEEDBACK_GIVEN"
GOAL_CREATED = "GOAL_CREATED"
GOAL_UPDATED = "GOAL_UPDATED"
GOAL_COMPLETED = "GOAL_COMPLETED"

ALL_EVENT_TYPES: List[str] = [
    SESSION_STARTED, SESSION_ENDED, COURSE_OPENED, TOPIC_STARTED, TOPIC_COMPLETED,
    QUESTION_ASKED, EDUCATIONAL_QUESTION_ASKED, EXPLANATION_REQUESTED,
    EXPLANATION_DELIVERED, RE_EXPLAIN_REQUESTED, EXAMPLE_REQUESTED, ANALOGY_REQUESTED,
    SIMPLIFICATION_REQUESTED, DEEPER_EXPLANATION_REQUESTED, PREREQUISITE_REVIEWED,
    RESOURCE_OPENED, RESOURCE_COMPLETED, PLAN_CREATED, PLAN_UPDATED,
    PLAN_STEP_STARTED, PLAN_STEP_COMPLETED, SELF_REPORTED_UNDERSTANDING,
    SELF_REPORTED_CONFUSION, TEACHING_MODE_SWITCHED, FEEDBACK_GIVEN,
    GOAL_CREATED, GOAL_UPDATED, GOAL_COMPLETED,
]

# 默认证据强度（可按事件覆盖）
DEFAULT_STRENGTH: Dict[str, EvidenceStrength] = {
    SESSION_STARTED: "weak", SESSION_ENDED: "weak", COURSE_OPENED: "weak",
    TOPIC_STARTED: "weak", TOPIC_COMPLETED: "weak", QUESTION_ASKED: "weak",
    EDUCATIONAL_QUESTION_ASKED: "medium", EXPLANATION_REQUESTED: "weak",
    EXPLANATION_DELIVERED: "medium", RE_EXPLAIN_REQUESTED: "medium",
    EXAMPLE_REQUESTED: "medium", ANALOGY_REQUESTED: "medium",
    SIMPLIFICATION_REQUESTED: "medium", DEEPER_EXPLANATION_REQUESTED: "medium",
    PREREQUISITE_REVIEWED: "medium", RESOURCE_OPENED: "weak",
    RESOURCE_COMPLETED: "medium", PLAN_CREATED: "medium", PLAN_UPDATED: "medium",
    PLAN_STEP_STARTED: "weak", PLAN_STEP_COMPLETED: "medium",
    SELF_REPORTED_UNDERSTANDING: "weak", SELF_REPORTED_CONFUSION: "medium",
    TEACHING_MODE_SWITCHED: "medium", FEEDBACK_GIVEN: "medium",
    GOAL_CREATED: "medium", GOAL_UPDATED: "medium", GOAL_COMPLETED: "strong",
}

# 对画像更新有意义的证据（用于合作伙伴决定是否 refresh profile）
MEANINGFUL_FOR_PROFILE = {
    EDUCATIONAL_QUESTION_ASKED, EXPLANATION_DELIVERED, RE_EXPLAIN_REQUESTED,
    EXAMPLE_REQUESTED, ANALOGY_REQUESTED, SIMPLIFICATION_REQUESTED,
    DEEPER_EXPLANATION_REQUESTED, PREREQUISITE_REVIEWED, RESOURCE_COMPLETED,
    PLAN_CREATED, PLAN_UPDATED, PLAN_STEP_COMPLETED, SELF_REPORTED_UNDERSTANDING,
    SELF_REPORTED_CONFUSION, TEACHING_MODE_SWITCHED, FEEDBACK_GIVEN,
    GOAL_COMPLETED,
}

# ---------------------------------------------------------------------------
# Event 模型
# ---------------------------------------------------------------------------


class LearningEvent(BaseModel):
    """统一学习事件结构。"""

    schema_version: int = Field(default=1)
    event_version: int = Field(default=1)
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: str = Field(description="事件类型")
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    kc_id: str = Field(default="")
    session_id: str = Field(default="")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = Field(default="edu_agent", description="事件来源系统")
    evidence_strength: EvidenceStrength = Field(default="weak")
    meaningful_for_profile: bool = Field(default=False)
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        event_type = data.get("event_type", "")
        if "evidence_strength" not in data and event_type in DEFAULT_STRENGTH:
            data["evidence_strength"] = DEFAULT_STRENGTH[event_type]
        if "meaningful_for_profile" not in data:
            data["meaningful_for_profile"] = event_type in MEANINGFUL_FOR_PROFILE
        super().__init__(**data)


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------

_OUTBOX_KEY = "learning_event_outbox"


def _load_outbox() -> List[dict]:
    outbox = app_state_store.load(_OUTBOX_KEY, default=[])
    return outbox if isinstance(outbox, list) else []


def _save_outbox(outbox: List[dict]) -> None:
    app_state_store.save(_OUTBOX_KEY, outbox)


def emit_event(event: LearningEvent) -> str:
    """写入 Outbox（幂等：同 event_id 不重复入队）。返回 event_id。"""
    outbox = _load_outbox()
    existing_ids = {item.get("event_id") for item in outbox}
    if event.event_id in existing_ids:
        return event.event_id
    outbox.append(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "user_id": event.user_id,
            "course_id": event.course_id,
            "goal_id": event.goal_id,
            "kc_id": event.kc_id,
            "session_id": event.session_id,
            "timestamp": event.timestamp,
            "source": event.source,
            "evidence_strength": event.evidence_strength,
            "meaningful_for_profile": event.meaningful_for_profile,
            "payload": event.payload,
            "metadata": event.metadata,
            "delivery_state": "pending",
            "retry_count": 0,
            "next_retry_at": 0.0,
            "last_error": "",
        }
    )
    _save_outbox(outbox)
    return event.event_id


def build_event(
    event_type: str,
    user_id: str = "",
    course_id: str = "",
    goal_id: str = "",
    kc_id: str = "",
    session_id: str = "",
    payload: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> LearningEvent:
    """便捷构造器，自动填 evidence_strength / meaningful_for_profile。"""
    return LearningEvent(
        event_type=event_type,
        user_id=user_id,
        course_id=course_id,
        goal_id=goal_id,
        kc_id=kc_id,
        session_id=session_id,
        payload=payload or {},
        metadata=metadata or {},
    )


def flush_outbox(
    delivery_url: Optional[str] = None,
    api_key: str = "",
    timeout: float = 5.0,
    max_attempts: Optional[int] = None,
    max_batch: int = 20,
    retry_base_seconds: Optional[int] = None,
) -> Dict[str, int]:
    """尝试把 pending 事件投递给合作伙伴；失败留在队列中，退避重试。

    幂等：合作伙伴按 event_id 去重，重复投递无副作用。
    返回 {"delivered": n, "failed": n, "pending": n}。
    """
    from edu_agent.config.settings import get_settings

    settings = get_settings()
    if max_attempts is None:
        max_attempts = settings.learning_event_max_retries
    if retry_base_seconds is None:
        retry_base_seconds = settings.learning_event_retry_base_seconds

    if not delivery_url:
        return {"delivered": 0, "failed": 0, "pending": len(_load_outbox())}

    import urllib.error
    import urllib.request

    outbox = _load_outbox()
    now = time.time()
    delivered = 0
    failed = 0
    pending_items: List[dict] = []

    for item in outbox:
        if item.get("delivery_state") == "delivered":
            continue
        if item.get("next_retry_at", 0.0) > now:
            pending_items.append(item)
            continue
        # 超过最大重试次数 → 标记 failed，不再投递（保留记录）
        if item.get("retry_count", 0) >= max_attempts:
            item["delivery_state"] = "failed"
            pending_items.append(item)
            continue

        headers = {
            "User-Agent": "EduAgents-Events/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps(item, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(delivery_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout):
                item["delivery_state"] = "delivered"
                item["delivered_at"] = datetime.now(timezone.utc).isoformat()
                delivered += 1
        except (urllib.error.URLError, TimeoutError, OSError):
            item["retry_count"] = item.get("retry_count", 0) + 1
            item["next_retry_at"] = now + min(
                (retry_base_seconds or 2) ** item["retry_count"], 3600
            )  # 指数退避
            item["delivery_state"] = "pending"
            failed += 1
        pending_items.append(item)

        if delivered + failed >= max_batch:
            break

    _save_outbox(pending_items)
    return {"delivered": delivered, "failed": failed, "pending": len(pending_items)}
