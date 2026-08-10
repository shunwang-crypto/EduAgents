"""Profile Fact Updater：背景事实（会变化，不是只增不减）。

- 同一 fact_key 只存在一条（UNIQUE），新证据 UPDATE 而非追加。
- 支持 CREATE / UPDATE / REINFORCE（confidence 上升）/ DEACTIVATE / DELETE。
- 用户明确删除 → 真正 DELETE，change log 只留最小审计。
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
    return payload.get("fact_value") or payload.get("value") or True


def apply_profile_fact_evidence(
    repo: LearnerRepository, evidence: StructuredEvidence
) -> Dict[str, Any]:
    """处理 profile_fact 证据（entity_key=fact_key）。"""
    fact_key = evidence.entity_key
    if not fact_key:
        return {"operation": "NONE", "reason": "empty key"}
    user_id = evidence.user_id
    now = _now_iso()

    existing = repo.get_profile_fact(user_id, fact_key)

    if evidence.event_type == "PROFILE_FACT_DELETED":
        if existing:
            fact_id = existing["fact_id"]
            repo.delete_profile_fact(user_id, fact_id)
            return {"operation": "DELETE", "entity": f"fact:{fact_key}", "reason": "user requested"}
        return {"operation": "NONE", "reason": "not exists"}

    value = _value_of(evidence.payload or {})
    source = evidence.source
    confidence = 0.9 if source == "USER_EXPLICIT" else max(0.3, evidence.weight)

    if existing is None:
        fact_id = f"FACT-{uuid.uuid4().hex[:12]}"
        repo.upsert_profile_fact(
            {
                "fact_id": fact_id,
                "user_id": user_id,
                "category": (evidence.payload or {}).get("category", "background"),
                "fact_key": fact_key,
                "fact_value_json": json.dumps(value, ensure_ascii=False, default=str),
                "confidence": confidence,
                "source": source,
                "status": "active",
                "first_observed_at": now,
                "last_confirmed_at": now,
                "updated_at": now,
                "expires_at": None,
            }
        )
        return {"operation": "CREATE", "entity": f"fact:{fact_key}", "reason": evidence.event_type}

    # 冲突处理：同 key → UPDATE（不新增第二条）
    old_value = existing.get("fact_value_json")
    op = "UPDATE" if old_value != json.dumps(value, ensure_ascii=False, default=str) else "REINFORCE"
    repo.upsert_profile_fact(
        {
            "fact_id": existing["fact_id"],
            "user_id": user_id,
            "category": existing.get("category") or "background",
            "fact_key": fact_key,
            "fact_value_json": json.dumps(value, ensure_ascii=False, default=str),
            "confidence": max(float(existing.get("confidence", 0.3)), confidence),
            "source": source,
            "status": "active",
            "first_observed_at": existing.get("first_observed_at") or now,
            "last_confirmed_at": now,
            "updated_at": now,
            "expires_at": existing.get("expires_at"),
        }
    )
    return {"operation": op, "entity": f"fact:{fact_key}", "reason": evidence.event_type}


def deactivate_fact(
    repo: LearnerRepository, user_id: str, fact_key: str, reason: str = "model judgment"
) -> Dict[str, Any]:
    """模型认为失效（可追踪，不删除数据）。"""
    existing = repo.get_profile_fact(user_id, fact_key)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists"}
    repo.upsert_profile_fact(
        {
            **existing,
            "status": "inactive",
            "updated_at": _now_iso(),
        }
    )
    return {"operation": "DEACTIVATE", "entity": f"fact:{fact_key}", "reason": reason}


def delete_fact_direct(
    repo: LearnerRepository, user_id: str, fact_key: str
) -> Dict[str, Any]:
    """用户明确删除：真正 DELETE（change log 由 service 记最小审计）。"""
    existing = repo.get_profile_fact(user_id, fact_key)
    if existing is None:
        return {"operation": "NONE", "reason": "not exists"}
    repo.delete_profile_fact(user_id, existing["fact_id"])
    return {"operation": "DELETE", "entity": f"fact:{fact_key}", "reason": "user requested"}
