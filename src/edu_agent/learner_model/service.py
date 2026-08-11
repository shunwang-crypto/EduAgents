"""Learner Model Service：业务门面（范围收缩版）。

统一管线：
  ingest_event / 显式操作
  → with repo.transaction():
      insert event（幂等）
      apply targeted updater（before → update → after）
      change log（before/after；敏感 DELETE 最小审计）
      bump version（global / course，按 scope 各一次）
      COMMIT / ROLLBACK

事件类型（收缩）：COURSE_CREATED/UPDATED/DELETED、GOAL_CREATED/UPDATED、
PLAN_CREATED/UPDATED、PLAN_STEP_STARTED/COMPLETED、CHAT_MESSAGE_SENT、
USER_EXPLICIT_PROFILE_FACT、USER_EXPLICIT_PREFERENCE、PROFILE_FACT_DELETED、
MEMORY_CREATED、MEMORY_DELETED。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.config.settings import get_settings
from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import (
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
    KnowledgeItem,
    LearnerStateBundle,
    LearningContext,
    ModeScore,
    Preferences,
    Profile,
    SemanticMemoryItem,
)
from edu_agent.learner_model.sqlite_repository import SQLiteLearnerRepository
from edu_agent.learner_model.updaters import (
    goal as goal_updater,
    knowledge as knowledge_updater,
    preference as preference_updater,
    profile_fact as profile_fact_updater,
)

DEFAULT_USER_ID = "STU-001"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    return f"EV-{uuid.uuid4().hex[:12]}"


class LearnerModelService:
    """本地 Dynamic Learner Model 唯一入口。

    默认实例（无 db_path）进程内共享同一连接，避免多连接 WAL 锁；
    显式 db_path 的实例独立连接（测试/多库场景）。
    """

    _shared_default: Optional["LearnerModelService"] = None

    def __init__(
        self,
        db_path: Optional[str] = None,
        repo: Optional[LearnerRepository] = None,
    ) -> None:
        if db_path is None and repo is None:
            shared = LearnerModelService._shared_default
            if shared is not None:
                self._repo = shared._repo
                self._auto_update = shared._auto_update
                return
            settings = get_settings()
            self._repo = SQLiteLearnerRepository(settings.learner_model_db_path)
            self._auto_update = settings.learner_model_auto_update
            LearnerModelService._shared_default = self
            return
        settings = get_settings()
        self._repo = repo or SQLiteLearnerRepository(db_path or settings.learner_model_db_path)
        self._auto_update = settings.learner_model_auto_update

    @property
    def repo(self) -> LearnerRepository:
        return self._repo

    def close(self) -> None:
        conn = getattr(self._repo, "_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "LearnerModelService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def ensure_learner(self, user_id: str = DEFAULT_USER_ID, display_name: str = "") -> None:
        self._repo.ensure_learner(user_id, display_name)

    def ensure_course(self, user_id: str, course_id: str) -> None:
        """首次访问课程时建立 course state。course_id 为空直接忽略。"""
        if not course_id:
            return
        self.ensure_learner(user_id)
        if self._repo.get_course_state(user_id, course_id) is None:
            self._repo.upsert_course_state(
                {"user_id": user_id, "course_id": course_id, "current_goal_id": "",
                 "progress": 0.0, "current_stage": "", "state_version": 1,
                 "updated_at": _now_iso()}
            )

    # ------------------------------------------------------------------
    # Event 入口
    # ------------------------------------------------------------------
    def ingest_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """统一事件入口（auto_update 决定 apply 或 record-only）。"""
        if self._auto_update:
            return self.apply_event(event)
        if event.get("course_id"):
            self.ensure_course(event["user_id"], event["course_id"])
        self.record_event(event)
        return []

    def record_event(self, event: Dict[str, Any]) -> str:
        event_id = event.get("event_id") or _new_event_id()
        timestamp = event.get("timestamp") or _now_iso()
        self._repo.insert_event(
            {"event_id": event_id, "schema_version": 1,
             "event_type": event.get("event_type", ""),
             "user_id": event.get("user_id", ""),
             "course_id": event.get("course_id", ""),
             "goal_id": event.get("goal_id", ""),
             "kc_id": event.get("kc_id", ""),
             "session_id": event.get("session_id", ""),
             "timestamp": timestamp, "source": event.get("source", "SYSTEM_OBSERVATION"),
             "evidence_strength": event.get("evidence_strength", "weak"),
             "payload_json": json.dumps(event.get("payload", {}), ensure_ascii=False, default=str),
             "created_at": timestamp}
        )
        return event_id

    def apply_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """记录事件并更新画像（单事务 + 幂等）。"""
        event_id = event.get("event_id") or _new_event_id()
        event = {**event, "event_id": event_id}
        if not event.get("timestamp"):
            event["timestamp"] = _now_iso()

        if self._repo.event_exists(event_id):
            return []  # 幂等

        user_id = event.get("user_id", "")
        course_id = event.get("course_id", "")
        if course_id:
            self.ensure_course(user_id, course_id)
        else:
            self.ensure_learner(user_id)

        changes: List[Dict[str, Any]] = []
        with self._repo.transaction():
            self._repo.insert_event(
                {"event_id": event_id, "schema_version": 1,
                 "event_type": event.get("event_type", ""),
                 "user_id": user_id, "course_id": course_id,
                 "goal_id": event.get("goal_id", ""),
                 "kc_id": event.get("kc_id", ""),
                 "session_id": event.get("session_id", ""),
                 "timestamp": event["timestamp"],
                 "source": event.get("source", "SYSTEM_OBSERVATION"),
                 "evidence_strength": event.get("evidence_strength", "weak"),
                 "payload_json": json.dumps(event.get("payload", {}), ensure_ascii=False, default=str),
                 "created_at": event["timestamp"]}
            )
            change = self._apply_event(event)
            if change.get("operation") != "NONE":
                changes.append(change)
                self._log_change(event, change)

            bump_course = change.get("scope") == "course" and course_id
            bump_global = change.get("scope") == "global"
            if bump_course:
                self._repo.bump_state_version(user_id, course_id)
            if bump_global:
                self._repo.bump_global_version(user_id)

        return changes

    def _apply_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """事件 → 定向更新（无消费方实体不再处理）。"""
        etype = event.get("event_type", "")
        payload = event.get("payload", {}) or {}
        user_id = event.get("user_id", "")
        course_id = event.get("course_id", "")
        kc_id = event.get("kc_id", "") or payload.get("kc_id", "")

        if etype == "USER_EXPLICIT_PROFILE_FACT":
            return profile_fact_updater.apply_profile_fact_evidence(
                self._repo,
                _mk_evidence(user_id, course_id, "profile_fact",
                             payload.get("fact_key", ""), "pos", event),
            )
        if etype == "PROFILE_FACT_DELETED":
            return profile_fact_updater.apply_profile_fact_evidence(
                self._repo,
                _mk_evidence(user_id, course_id, "profile_fact",
                             payload.get("fact_key", ""), "neg", event),
            )
        if etype == "USER_EXPLICIT_PREFERENCE":
            key = payload.get("preference_key", "")
            direction = payload.get("direction", "pos")
            return preference_updater.apply_preference_evidence(
                self._repo,
                _mk_evidence(user_id, course_id, "preference", key, direction, event),
            )
        if etype in ("GOAL_CREATED", "GOAL_UPDATED"):
            return goal_updater.apply_goal_evidence(
                self._repo,
                _mk_evidence(user_id, course_id, "goal", payload.get("goal_id", ""), "neutral", event),
            )
        if etype in ("PLAN_CREATED", "PLAN_UPDATED", "PLAN_STEP_STARTED", "PLAN_STEP_COMPLETED"):
            return {"operation": "NONE", "scope": "course", "reason": etype}
        if etype in ("MEMORY_CREATED", "MEMORY_DELETED"):
            return {"operation": "NONE", "scope": "global", "reason": etype}
        if etype == "CHAT_MESSAGE_SENT" and kc_id:
            # 课程内聊天曝光：只更新时间/计数，不改 mastery
            return knowledge_updater.apply_knowledge_evidence(
                self._repo,
                _mk_evidence(user_id, course_id, "knowledge", kc_id, "neutral", event),
            )
        if etype == "COURSE_CREATED":
            return {"operation": "CREATE", "entity": f"course:{course_id}",
                    "before": None, "after": {"course_id": course_id},
                    "reason": "course created", "scope": "course"}
        return {"operation": "NONE", "scope": "course", "reason": f"unhandled {etype}"}

    def _log_change(self, event: Dict[str, Any], change: Dict[str, Any]) -> None:
        from edu_agent.learner_model.change_log import log_change

        op = change.get("operation", "UPDATE")
        sensitive_delete = op == "DELETE" and change.get("entity", "").startswith(("fact:", "memory:"))
        log_change(
            self._repo,
            event.get("user_id", ""),
            entity_type=change.get("entity", "").split(":")[0] or "learner_model",
            entity_id=change.get("entity", ""),
            operation=op,
            course_id=event.get("course_id", ""),
            reason=change.get("reason", "") or event.get("event_type", ""),
            before=None if sensitive_delete else change.get("before"),
            after=None if sensitive_delete else change.get("after"),
        )

    # ------------------------------------------------------------------
    # 显式操作（USER_EXPLICIT 优先；统一走 mutation pipeline）
    # ------------------------------------------------------------------
    def set_profile_fact(self, user_id: str, fact_key: str, fact_value: Any,
                         category: str = "background") -> Dict[str, Any]:
        changes = self.apply_event(
            {"event_type": "USER_EXPLICIT_PROFILE_FACT", "user_id": user_id,
             "source": "USER_EXPLICIT",
             "payload": {"fact_key": fact_key, "fact_value": fact_value, "category": category}}
        )
        return changes[0] if changes else {"operation": "NONE", "reason": "no change", "scope": "global"}

    def delete_profile_fact(self, user_id: str, fact_key: str) -> Dict[str, Any]:
        changes = self.apply_event(
            {"event_type": "PROFILE_FACT_DELETED", "user_id": user_id,
             "source": "USER_EXPLICIT",
             "payload": {"fact_key": fact_key}}
        )
        return changes[0] if changes else {"operation": "NONE", "reason": "no change", "scope": "global"}

    def set_preference(self, user_id: str, preference_key: str, score: Optional[float] = None,
                       direction: str = "pos", course_id: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {"preference_key": preference_key}
        if score is not None:
            payload["score"] = score
        else:
            payload["direction"] = direction
        changes = self.apply_event(
            {"event_type": "USER_EXPLICIT_PREFERENCE", "user_id": user_id, "course_id": course_id,
             "source": "USER_EXPLICIT",
             "payload": payload}
        )
        return changes[0] if changes else {"operation": "NONE", "reason": "no change", "scope": "global"}

    def add_memory(self, user_id: str, content: str, course_id: str = "",
                   category: str = "experience") -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        result = memory_updater.add_memory(self._repo, user_id, content, course_id, category)
        if result.get("operation") != "NONE":
            self._repo.bump_global_version(user_id)
            from edu_agent.learner_model.change_log import log_change

            log_change(self._repo, user_id, entity_type="semantic_memory",
                       entity_id=result.get("entity", ""), operation=result["operation"],
                       course_id=course_id, reason=result.get("reason", ""),
                       before=result.get("before"), after=result.get("after"))
            self.record_event({"event_type": "MEMORY_CREATED", "user_id": user_id,
                               "course_id": course_id, "payload": {"content": content[:80]}})
        return result

    def delete_memory(self, user_id: str, memory_id: str) -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        result = memory_updater.delete_memory_direct(self._repo, user_id, memory_id)
        if result.get("operation") == "DELETE":
            self._repo.bump_global_version(user_id)
            from edu_agent.learner_model.change_log import log_change

            log_change(self._repo, user_id, entity_type="semantic_memory",
                       entity_id=memory_id, operation="DELETE", reason="user requested")
            self.record_event({"event_type": "MEMORY_DELETED", "user_id": user_id,
                               "payload": {"memory_id": memory_id}})
        return result

    def upsert_goal(self, user_id: str, goal_id: str, course_id: str, name: str,
                    target: str = "", priority: Optional[int] = None,
                    target_kcs: Optional[List[str]] = None) -> Dict[str, Any]:
        if not goal_id:
            goal_id = f"GOAL-{user_id}-{course_id}"
        if course_id:
            self.ensure_course(user_id, course_id)
        result = goal_updater.upsert_goal(self._repo, user_id, goal_id, course_id,
                                          name, target, priority, target_kcs)
        if result.get("operation") != "NONE":
            from edu_agent.learner_model.change_log import log_change

            log_change(self._repo, user_id, entity_type="goal",
                       entity_id=result.get("entity", ""), operation=result["operation"],
                       course_id=course_id, reason=result.get("reason", ""),
                       before=result.get("before"), after=result.get("after"))
            if course_id:
                self._repo.bump_state_version(user_id, course_id)
            self.record_event({"event_type": "GOAL_CREATED" if result["operation"] == "CREATE" else "GOAL_UPDATED",
                               "user_id": user_id, "course_id": course_id,
                               "payload": {"goal_id": goal_id, "name": name}})
        return result

    def set_goal_status(self, user_id: str, goal_id: str, status: str) -> Dict[str, Any]:
        return goal_updater.set_goal_status(self._repo, user_id, goal_id, status)

    def update_goal_progress(self, user_id: str, goal_id: str, progress: float) -> Dict[str, Any]:
        return goal_updater.update_goal_progress(self._repo, user_id, goal_id, progress)

    def update_course_progress(self, user_id: str, course_id: str, progress: float,
                               stage: str = "") -> None:
        if not course_id:
            return
        existing = self._repo.get_course_state(user_id, course_id) or {}
        self._repo.upsert_course_state(
            {"user_id": user_id, "course_id": course_id,
             "current_goal_id": existing.get("current_goal_id", ""),
             "progress": max(0.0, min(1.0, progress)),
             "current_stage": stage or existing.get("current_stage", ""),
             "state_version": existing.get("state_version", 1),
             "updated_at": _now_iso()}
        )

    def set_current_goal(self, user_id: str, course_id: str, goal_id: str) -> None:
        if not course_id:
            return
        existing = self._repo.get_course_state(user_id, course_id) or {}
        self._repo.upsert_course_state(
            {"user_id": user_id, "course_id": course_id, "current_goal_id": goal_id,
             "progress": existing.get("progress", 0.0),
             "current_stage": existing.get("current_stage", ""),
             "state_version": existing.get("state_version", 1),
             "updated_at": _now_iso()}
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def build_bundle(self, user_id: str, course_id: str = "") -> LearnerStateBundle:
        """从 SQLite 组装 LearnerStateBundle（无 course 时只取全局）。"""
        learner = self._repo.get_learner(user_id) or {}
        course_row = self._repo.get_course_state(user_id, course_id) if course_id else None

        global_state = GlobalLearnerState(
            profile=Profile(user_id=user_id,
                            display_name=learner.get("display_name", ""),
                            education_level=learner.get("education_level", ""),
                            language=learner.get("language", "zh"),
                            background=learner.get("background", "")),
            goals=[Goal(**self._goal_row(g)) for g in self._repo.list_goals(user_id)],
            preferences=self._build_preferences(user_id, course_id),
            semantic_memory=[
                SemanticMemoryItem(content=m.get("content", ""), created_at=m.get("updated_at", ""))
                for m in self._repo.list_global_memories(user_id)
                if m.get("status") in ("active", "candidate")
            ],
        )

        knowledge: List[KnowledgeItem] = []
        if course_row:
            knowledge = [
                KnowledgeItem(kc_id=k.get("kc_id"), name=k.get("kc_name") or k.get("kc_id"),
                              mastery=k.get("mastery"), confidence=k.get("confidence"),
                              status=k.get("status") or "unknown", trend=k.get("trend"),
                              evidence_count=k.get("evidence_count"),
                              last_evidence_at=k.get("last_evidence_at"),
                              is_estimated=bool(k.get("is_estimated", 0)))
                for k in self._repo.list_kcs(user_id, course_id)
            ]

        course_state = CourseLearnerState(
            user_id=user_id, course_id=course_id or "",
            goal_id=(course_row or {}).get("current_goal_id", ""),
            progress=float((course_row or {}).get("progress", 0.0)),
            knowledge=knowledge,
            state_version=(course_row or {}).get("state_version"),
            updated_at=(course_row or {}).get("updated_at"),
            freshness="fresh",
        )

        active_goal = None
        for g in self._repo.list_goals(user_id, status="active"):
            if not course_id or g.get("course_id") in ("", course_id):
                active_goal = Goal(**self._goal_row(g))
                break

        return LearnerStateBundle(
            user_id=user_id, course_id=course_id,
            global_state=global_state, course_state=course_state, active_goal=active_goal,
            global_state_version=learner.get("global_state_version"),
            course_state_version=(course_row or {}).get("state_version"),
        )

    def _goal_row(self, row: dict) -> dict:
        try:
            target_kcs = json.loads(row.get("target_kcs_json") or "[]")
        except (ValueError, TypeError):
            target_kcs = []
        return {"goal_id": row.get("goal_id"), "course_id": row.get("course_id", ""),
                "goal_name": row.get("name"), "target": row.get("target", ""),
                "priority": row.get("priority", 1), "status": row.get("status", "active"),
                "progress": float(row.get("progress", 0.0)), "target_kcs": target_kcs}

    def _build_preferences(self, user_id: str, course_id: str = "") -> Preferences:
        rows = self._repo.list_preferences(user_id, course_id)
        mode_effectiveness: Dict[str, ModeScore] = {}
        best_key, best_score = "", 0.0
        for r in rows:
            if r.get("status") == "inactive":
                continue
            key = r["preference_key"]
            score = float(r.get("score", 0.5))
            confidence = float(r.get("confidence", 0.0))
            mode_effectiveness[key] = ModeScore(score=score, confidence=confidence,
                                                sample_size=int(r.get("evidence_count", 0)))
            if confidence >= 0.5 and score * confidence > best_score:
                best_score = score * confidence
                best_key = key
        return Preferences(preferred_mode=best_key, mode_effectiveness=mode_effectiveness)

    def get_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        return self._repo.list_changes(user_id, course_id=course_id, limit=limit)

    def get_events(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]:
        return self._repo.list_events(user_id, course_id=course_id, limit=limit)


def _mk_evidence(user_id: str, course_id: str, entity_type: str, entity_key: str,
                 direction: str, event: Dict[str, Any]) -> Any:
    """构造轻量 evidence（兼容 updater 接口）。"""
    from edu_agent.learner_model.evidence_light import LightEvidence

    return LightEvidence(
        user_id=user_id, course_id=course_id, entity_type=entity_type,
        entity_key=entity_key, direction=direction,
        event_type=event.get("event_type", ""),
        source=event.get("source", "SYSTEM_OBSERVATION"),
        payload=event.get("payload", {}) or {},
        weight=0.9 if event.get("source") == "USER_EXPLICIT" else 0.3,
    )
