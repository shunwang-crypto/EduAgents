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


def apply_tutoring_evidence(
    repo: LearnerRepository, evidence: Dict[str, Any]
) -> Dict[str, Any]:
    """处理一条 tutor 教学证据（确定性 mastery 更新）。

    evidence 必须包含：
      user_id / course_id / kc_id / correctness / difficulty / hint_level /
      confidence（诊断置信度） / misconceptions / evidence_type / teaching_action

    mastery 由 mastery.py 的 compute_mastery_delta + apply_delta 计算，绝不接受
    LLM 直接给的 mastery 值。
    """
    from edu_agent.adaptive.thresholds import classify_status
    from edu_agent.workflows.tutoring.mastery import apply_delta, compute_mastery_delta

    user_id = evidence.get("user_id", "")
    course_id = evidence.get("course_id", "")
    kc_id = evidence.get("kc_id", "")
    if not kc_id or not user_id:
        return {"operation": "NONE", "reason": "missing kc/user", "scope": "course"}

    correctness = evidence.get("correctness", "incorrect")
    difficulty = int(evidence.get("difficulty", 1))
    hint_level = int(evidence.get("hint_level", 0))
    misconceptions = evidence.get("misconceptions") or []

    mastery_delta, conf_delta = compute_mastery_delta(
        correctness, difficulty, hint_level, misconceptions
    )

    # P1-6：弱证据（无法合理判断 / 规则不确定）不允许快速提高 mastery。
    # 即使判为 correct，weak evidence 也只给 0 增益（或负增益），绝不上涨。
    evidence_strength = (evidence.get("evidence_strength") or "medium").lower()
    if evidence_strength == "weak":
        mastery_delta = min(mastery_delta, 0.0)

    now = _now_iso()
    existing = repo.get_kc(user_id, course_id, kc_id)
    prev_mastery = existing.get("mastery") if existing else None
    prev_conf = existing.get("confidence") if existing else None

    new_mastery, new_conf = apply_delta(
        prev_mastery, prev_conf, mastery_delta, conf_delta
    )
    new_status = classify_status(new_mastery)

    if existing is None:
        repo.upsert_kc(
            {"user_id": user_id, "course_id": course_id, "kc_id": kc_id,
             "kc_name": evidence.get("kc_name") or kc_id,
             "mastery": new_mastery, "confidence": new_conf, "status": new_status,
             "trend": None, "evidence_count": 1, "first_evidence_at": now,
             "last_evidence_at": now, "is_estimated": 0,
             "created_at": now, "updated_at": now}
        )
        return {"operation": "CREATE", "entity": f"kc:{kc_id}", "before": None,
                "after": {"mastery": new_mastery, "confidence": new_conf, "status": new_status},
                "reason": "first tutoring evidence", "scope": "course"}

    repo.upsert_kc(
        {"user_id": user_id, "course_id": course_id, "kc_id": kc_id,
         "kc_name": existing.get("kc_name") or kc_id,
         "mastery": new_mastery, "confidence": new_conf, "status": new_status,
         "trend": existing.get("trend"),
         "evidence_count": int(existing.get("evidence_count", 0)) + 1,
         "first_evidence_at": existing.get("first_evidence_at") or now,
         "last_evidence_at": now, "is_estimated": existing.get("is_estimated", 0),
         "created_at": existing.get("created_at") or now, "updated_at": now}
    )
    return {"operation": "UPDATE", "entity": f"kc:{kc_id}",
            "before": {"mastery": prev_mastery, "confidence": prev_conf,
                       "status": existing.get("status")},
            "after": {"mastery": new_mastery, "confidence": new_conf, "status": new_status},
            "reason": f"tutoring {correctness}", "scope": "course"}
