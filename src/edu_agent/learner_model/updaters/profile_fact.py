"""Profile Fact Updater（范围收缩版）：背景事实，同 key 唯一，显式修正重设 confidence。

- 合法值 False/0/"" 正确保存（显式 key 判断，不用 or）。
- 用户显式修正：confidence 重设（不保留旧 max 误导）。
- scope：global。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from edu_agent.learner_model.evidence_light import LightEvidence
from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value_of(payload: dict) -> Any:
    if "fact_value" in payload:
        return payload["fact_value"]
    if "value" in payload:
        return payload["value"]
    return True


def apply_profile_fact_evidence(
    repo: LearnerRepository, evidence: LightEvidence
) -> Dict[str, Any]:
    fact_key = evidence.entity_key
    if not fact_key:
        return {"operation": "NONE", "reason": "empty key", "scope": "global"}
    user_id = evidence.user_id
    now = _now_iso()

    existing = repo.get_profile_fact(user_id, fact_key)

    # 正负冲突互消（同一事务内，由 apply_event 包裹）：skill:x ↔ no_x 不能同时 active
    conflict_key = None
    if fact_key.startswith("skill:"):
        conflict_key = "no_" + fact_key[len("skill:"):]  # skill:python → no_python
    elif fact_key.startswith("no_"):
        conflict_key = "skill:" + fact_key[len("no_"):]  # no_python → skill:python
    if conflict_key:
        conflict = repo.get_profile_fact(user_id, conflict_key)
        if conflict and conflict.get("status") == "active":
            repo.delete_profile_fact(user_id, conflict["fact_id"])

    if evidence.event_type == "PROFILE_FACT_DELETED":
        if existing:
            repo.delete_profile_fact(user_id, existing["fact_id"])
            return {"operation": "DELETE", "entity": f"fact:{fact_key}",
                    "before": None, "after": None, "reason": "user requested", "scope": "global"}
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}

    value = _value_of(evidence.payload or {})
    is_user_explicit = evidence.source == "USER_EXPLICIT"

    if existing is None:
        fact_id = f"FACT-{uuid.uuid4().hex[:12]}"
        repo.upsert_profile_fact(
            {"fact_id": fact_id, "user_id": user_id,
             "category": (evidence.payload or {}).get("category", "background"),
             "fact_key": fact_key,
             "fact_value_json": json.dumps(value, ensure_ascii=False, default=str),
             "confidence": 0.9 if is_user_explicit else max(0.3, evidence.weight),
             "source": evidence.source, "status": "active",
             "first_observed_at": now, "last_confirmed_at": now, "updated_at": now,
             "expires_at": None}
        )
        return {"operation": "CREATE", "entity": f"fact:{fact_key}", "before": None,
                "after": {"value": value, "confidence": 0.9 if is_user_explicit else max(0.3, evidence.weight)},
                "reason": evidence.event_type, "scope": "global"}

    before: Dict[str, Any] = {"value": existing.get("fact_value_json"),
                              "confidence": float(existing.get("confidence", 0.3)),
                              "status": existing.get("status")}
    new_value_json = json.dumps(value, ensure_ascii=False, default=str)
    op = "UPDATE" if existing.get("fact_value_json") != new_value_json else "REINFORCE"
    confidence = 0.9 if is_user_explicit else max(float(existing.get("confidence", 0.3)), evidence.weight)
    repo.upsert_profile_fact(
        {"fact_id": existing["fact_id"], "user_id": user_id,
         "category": (evidence.payload or {}).get("category") or existing.get("category") or "background",
         "fact_key": fact_key, "fact_value_json": new_value_json, "confidence": confidence,
         "source": evidence.source, "status": "active",
         "first_observed_at": existing.get("first_observed_at") or now,
         "last_confirmed_at": now, "updated_at": now, "expires_at": existing.get("expires_at")}
    )
    return {"operation": op, "entity": f"fact:{fact_key}", "before": before,
            "after": {"value": value, "confidence": confidence, "status": "active"},
            "reason": evidence.event_type, "scope": "global"}


def delete_fact_direct(repo: LearnerRepository, user_id: str, fact_key: str) -> Dict[str, Any]:
    existing = repo.get_profile_fact(user_id, fact_key)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}
    repo.delete_profile_fact(user_id, existing["fact_id"])
    return {"operation": "DELETE", "entity": f"fact:{fact_key}",
            "before": None, "after": None, "reason": "user requested", "scope": "global"}
