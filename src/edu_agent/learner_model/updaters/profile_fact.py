"""Profile Fact Updater：背景事实（可变化，不重复追加）。

- 同一 fact_key 只存在一条（UNIQUE），新证据 UPDATE 而非追加。
- 合法值 False/0/"" 必须正确保存（显式 key 判断，不能用 or）。
- 用户显式修正：confidence 重设（不保留旧 max 造成误导）。
- 支持 CREATE / UPDATE / REINFORCE / DEACTIVATE / DELETE。
- scope：global。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from edu_agent.learner_model.evidence.schemas import StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value_of(payload: dict) -> Any:
    """显式 key 判断：False/0/"" 是合法值，不允许被 or True 吞掉。"""
    if "fact_value" in payload:
        return payload["fact_value"]
    if "value" in payload:
        return payload["value"]
    return True


def apply_profile_fact_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理 profile_fact 证据（entity_key=fact_key）。"""
    fact_key = evidence.entity_key
    if not fact_key:
        return {"operation": "NONE", "reason": "empty key", "scope": "global"}
    user_id = evidence.user_id
    now = _now_iso()

    existing = repo.get_profile_fact(user_id, fact_key)

    if evidence.event_type == "PROFILE_FACT_DELETED":
        if existing:
            repo.delete_profile_fact(user_id, existing["fact_id"])
            return {
                "operation": "DELETE",
                "entity": f"fact:{fact_key}",
                "before": None,  # 隐私：不保存被删内容
                "after": None,
                "reason": "user requested",
                "scope": "global",
            }
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}

    value = _value_of(evidence.payload or {})
    source = evidence.source
    is_user_explicit = source == "USER_EXPLICIT"

    if existing is None:
        fact_id = f"FACT-{uuid.uuid4().hex[:12]}"
        repo.upsert_profile_fact(
            {
                "fact_id": fact_id,
                "user_id": user_id,
                "category": (evidence.payload or {}).get("category", "background"),
                "fact_key": fact_key,
                "fact_value_json": json.dumps(value, ensure_ascii=False, default=str),
                "confidence": 0.9 if is_user_explicit else max(0.3, evidence.weight),
                "source": source,
                "status": "active",
                "first_observed_at": now,
                "last_confirmed_at": now,
                "updated_at": now,
                "expires_at": None,
            }
        )
        return {
            "operation": "CREATE",
            "entity": f"fact:{fact_key}",
            "before": None,
            "after": {"value": value, "confidence": 0.9 if is_user_explicit else max(0.3, evidence.weight)},
            "reason": evidence.event_type,
            "scope": "global",
        }

    before: Dict[str, Any] = {
        "value": existing.get("fact_value_json"),
        "confidence": float(existing.get("confidence", 0.3)),
        "status": existing.get("status"),
    }
    new_value_json = json.dumps(value, ensure_ascii=False, default=str)
    op = "UPDATE" if existing.get("fact_value_json") != new_value_json else "REINFORCE"
    if is_user_explicit:
        # 用户显式修正：confidence 重设（不保留旧高置信误导）
        confidence = 0.9
    else:
        confidence = max(float(existing.get("confidence", 0.3)), evidence.weight)
    repo.upsert_profile_fact(
        {
            "fact_id": existing["fact_id"],
            "user_id": user_id,
            "category": (evidence.payload or {}).get("category") or existing.get("category") or "background",
            "fact_key": fact_key,
            "fact_value_json": new_value_json,
            "confidence": confidence,
            "source": source,
            "status": "active",
            "first_observed_at": existing.get("first_observed_at") or now,
            "last_confirmed_at": now,
            "updated_at": now,
            "expires_at": existing.get("expires_at"),
        }
    )
    return {
        "operation": op,
        "entity": f"fact:{fact_key}",
        "before": before,
        "after": {"value": value, "confidence": confidence, "status": "active"},
        "reason": evidence.event_type,
        "scope": "global",
    }


def deactivate_fact(
    repo: LearnerRepository, user_id: str, fact_key: str, reason: str = "model judgment"
) -> Dict[str, Any]:
    existing = repo.get_profile_fact(user_id, fact_key)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}
    repo.upsert_profile_fact({**existing, "status": "inactive", "updated_at": _now_iso()})
    return {
        "operation": "DEACTIVATE",
        "entity": f"fact:{fact_key}",
        "before": {"status": existing.get("status")},
        "after": {"status": "inactive"},
        "reason": reason,
        "scope": "global",
    }


def delete_fact_direct(
    repo: LearnerRepository, user_id: str, fact_key: str
) -> Dict[str, Any]:
    """用户明确删除：真正 DELETE（change log 由 service 记最小审计）。"""
    existing = repo.get_profile_fact(user_id, fact_key)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists", "scope": "global"}
    repo.delete_profile_fact(user_id, existing["fact_id"])
    return {
        "operation": "DELETE",
        "entity": f"fact:{fact_key}",
        "before": None,
        "after": None,
        "reason": "user requested",
        "scope": "global",
    }
