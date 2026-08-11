"""Knowledge State Updater（范围收缩版）。

- 只有曝光证据：聊天中提到课程知识点时更新 last_evidence_at / evidence_count。
- mastery=None = UNKNOWN（不编造）；没有任何强证据来源，绝不自动提高 mastery。
- 删除：CHECK_UNDERSTANDING 强证据、能力/误解联动（无消费方）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from edu_agent.learner_model.evidence_light import LightEvidence
from edu_agent.learner_model.repository import LearnerRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_knowledge_evidence(
    repo: LearnerRepository, evidence: LightEvidence
) -> Dict[str, Any]:
    """处理一条 knowledge 曝光证据，返回变更描述。"""
    kc_id = evidence.entity_key
    if not kc_id:
        return {"operation": "NONE", "reason": "empty kc", "scope": "course"}
    user_id, course_id = evidence.user_id, evidence.course_id
    now = _now_iso()

    existing = repo.get_kc(user_id, course_id, kc_id)
    if existing is None:
        repo.upsert_kc(
            {"user_id": user_id, "course_id": course_id, "kc_id": kc_id,
             "kc_name": evidence.payload.get("kc_name") or kc_id,
             "mastery": None, "confidence": None, "status": "unknown", "trend": None,
             "evidence_count": 1, "first_evidence_at": now, "last_evidence_at": now,
             "is_estimated": 0, "created_at": now, "updated_at": now}
        )
        return {"operation": "CREATE", "entity": f"kc:{kc_id}", "before": None,
                "after": {"mastery": None, "status": "unknown"}, "reason": "first exposure",
                "scope": "course"}

    repo.upsert_kc(
        {"user_id": user_id, "course_id": course_id, "kc_id": kc_id,
         "kc_name": existing.get("kc_name") or kc_id,
         "mastery": existing.get("mastery"), "confidence": existing.get("confidence"),
         "status": existing.get("status", "unknown"), "trend": existing.get("trend"),
         "evidence_count": int(existing.get("evidence_count", 0)) + 1,
         "first_evidence_at": existing.get("first_evidence_at") or now,
         "last_evidence_at": now, "is_estimated": existing.get("is_estimated", 0),
         "created_at": existing.get("created_at") or now, "updated_at": now}
    )
    return {"operation": "UPDATE", "entity": f"kc:{kc_id}",
            "before": {"last_evidence_at": existing.get("last_evidence_at")},
            "after": {"last_evidence_at": now}, "reason": f"{evidence.event_type} exposure",
            "scope": "course"}
