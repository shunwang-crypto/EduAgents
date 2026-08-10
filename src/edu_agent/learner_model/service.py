"""Learner Model Service：业务门面。

统一管线（PHASE5）：
  ingest_event / 显式操作
  → with repo.transaction():
      insert event（幂等）
      extract evidences（规则 + 语义候选）
      insert evidences（幂等）
      apply updaters（before → update → after）
      change log（含 before/after，敏感 DELETE 只留最小审计）
      bump version（global / course，按 scope）
      maybe snapshot（按版本触发）
      COMMIT / ROLLBACK

- 禁止 course_id='' 创建课程状态：全局事件只 ensure learner。
- ingest_event：按 LEARNER_MODEL_AUTO_UPDATE 决定 apply 或 record-only。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from edu_agent.config.settings import get_settings
from edu_agent.learner_model.evidence.extractor import build_event, extract_evidence
from edu_agent.learner_model.evidence.schemas import LearningEvent, StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import (
    AbilityItem,
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
    KnowledgeItem,
    LearnerStateBundle,
    LearningContext,
    Misconception,
    ModeScore,
    Preferences,
    Profile,
    SemanticMemoryItem,
)
from edu_agent.learner_model.sqlite_repository import SQLiteLearnerRepository
from edu_agent.learner_model.updaters import (
    goal as goal_updater,
    knowledge as knowledge_updater,
    misconception as misconception_updater,
    preference as preference_updater,
    profile_fact as profile_fact_updater,
)

DEFAULT_USER_ID = "STU-001"
DEFAULT_COURSE_ID = "JAVA-OOP"

_KNOWLEDGE_TYPES = {"knowledge"}
_PREFERENCE_TYPES = {"preference"}
_MISCONCEPTION_TYPES = {"misconception"}
_PROFILE_FACT_TYPES = {"profile_fact"}
_GOAL_TYPES = {"goal"}
_ABILITY_TYPES = {"ability"}
_GLOBAL_SCOPE_TYPES = _PROFILE_FACT_TYPES | {"semantic_memory"}


class LearnerModelService:
    """本地 Dynamic Learner Model 唯一入口。"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        repo: Optional[LearnerRepository] = None,
    ) -> None:
        settings = get_settings()
        self._repo = repo or SQLiteLearnerRepository(db_path or settings.learner_model_db_path)
        self._auto_update = settings.learner_model_auto_update
        self._semantic_inference = settings.learner_model_semantic_inference_enabled
        self._snapshot_interval = max(1, settings.learner_model_snapshot_interval)

    @property
    def repo(self) -> LearnerRepository:
        return self._repo

    def close(self) -> None:
        """释放底层 SQLite 连接。"""
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

    def ensure_course(self, user_id: str = DEFAULT_USER_ID, course_id: str = DEFAULT_COURSE_ID) -> None:
        """首次访问课程时建立 course state（不编造数据）。course_id 为空直接忽略。"""
        if not course_id:
            return
        self.ensure_learner(user_id)
        if self._repo.get_course_state(user_id, course_id) is None:
            self._repo.upsert_course_state(
                {
                    "user_id": user_id,
                    "course_id": course_id,
                    "current_goal_id": "",
                    "progress": 0.0,
                    "current_stage": "",
                    "state_version": 1,
                    "updated_at": _now_iso(),
                }
            )

    # ------------------------------------------------------------------
    # Event 入口（统一）
    # ------------------------------------------------------------------
    def ingest_event(self, event: LearningEvent) -> List[Dict[str, Any]]:
        """统一事件入口：auto_update=True → 应用证据闭环；否则只记录。"""
        if self._auto_update:
            return self.apply_event(event)
        if event.course_id:
            self.ensure_course(event.user_id, event.course_id)
        self.record_event(event)
        return []

    def record_event(self, event: LearningEvent) -> str:
        """写一条 Event（append-only，返回 event_id）。"""
        if not event.event_id:
            event.event_id = f"EV-{_now_iso().replace(':', '').replace('.', '').replace('-', '')}"
        if not event.timestamp:
            event.timestamp = _now_iso()
        self._repo.insert_event(self._event_row(event))
        return event.event_id

    def _event_row(self, event: LearningEvent) -> dict:
        return {
            "event_id": event.event_id,
            "schema_version": event.schema_version,
            "event_type": event.event_type,
            "user_id": event.user_id,
            "course_id": event.course_id,
            "goal_id": event.goal_id,
            "kc_id": event.kc_id,
            "session_id": event.session_id,
            "timestamp": event.timestamp,
            "source": event.source,
            "evidence_strength": event.evidence_strength,
            "payload_json": json.dumps(event.payload, ensure_ascii=False, default=str),
            "created_at": event.timestamp,
        }

    # ------------------------------------------------------------------
    # 应用事件（事务 + 幂等 + 证据 + 版本 + 快照）
    # ------------------------------------------------------------------
    def apply_event(self, event: LearningEvent) -> List[Dict[str, Any]]:
        """记录事件并更新画像（单事务）。重复 event_id 返回 []（幂等）。"""
        if not event.event_id:
            event.event_id = f"EV-{_now_iso().replace(':', '').replace('.', '').replace('-', '')}"
        if not event.timestamp:
            event.timestamp = _now_iso()

        if self._repo.event_exists(event.event_id):
            return []  # 幂等：同一事件不重复应用

        # 课程事件需要课程状态；全局事件（course_id=''）只确保 learner
        if event.course_id:
            self.ensure_course(event.user_id, event.course_id)
        else:
            self.ensure_learner(event.user_id)

        changes: List[Dict[str, Any]] = []
        with self._repo.transaction():
            self._repo.insert_event(self._event_row(event))

            evidences = extract_evidence(event, use_semantic=self._semantic_inference)
            evidence_ids: List[str] = []
            for evidence in evidences:
                if self._evidence_row(evidence) is None:
                    continue
                inserted = self._repo.insert_evidence(self._evidence_row(evidence))
                if inserted:
                    evidence_ids.append(evidence.evidence_id)
                    change = self._apply_evidence(evidence)
                    if change.get("operation") != "NONE":
                        changes.append(change)
                        self._log_change(event, change, evidence_ids)

            # 统一版本递增：course/global 每个 scope 只 bump 一次（避免多次 change 重复递增）
            bump_course = any(
                c.get("scope") == "course" and c.get("operation") != "NONE"
                for c in changes
            )
            bump_global = any(
                c.get("scope") == "global" and c.get("operation") != "NONE"
                for c in changes
            )
            if bump_course and event.course_id:
                self._repo.bump_state_version(event.user_id, event.course_id)
            if bump_global:
                self._repo.bump_global_version(event.user_id)

            self._maybe_snapshot(event, changes)

        return changes

    def _evidence_row(self, evidence: StructuredEvidence) -> Optional[dict]:
        """证据行（幂等键 event+entity_type+entity_key+classifier_version）。"""
        if not evidence.evidence_id:
            return None
        return {
            "evidence_id": evidence.evidence_id,
            "event_id": evidence.event_id,
            "event_type": evidence.event_type,
            "user_id": evidence.user_id,
            "course_id": evidence.course_id,
            "kc_id": evidence.kc_id,
            "entity_type": evidence.entity_type,
            "entity_key": evidence.entity_key,
            "direction": evidence.direction,
            "weight": evidence.weight,
            "source": evidence.source,
            "classifier_version": (evidence.payload or {}).get("classifier_version", "rule-v1"),
            "confidence": (evidence.payload or {}).get("classifier_confidence"),
            "meaningful_for_profile": 1 if evidence.meaningful_for_profile else 0,
            "payload_json": json.dumps(evidence.payload, ensure_ascii=False, default=str),
            "created_at": evidence.timestamp,
        }

    def _apply_evidence(self, evidence: StructuredEvidence) -> Dict[str, Any]:
        et = evidence.entity_type
        if et in _KNOWLEDGE_TYPES:
            return knowledge_updater.apply_knowledge_evidence(self._repo, evidence)
        if et in _PREFERENCE_TYPES:
            return preference_updater.apply_preference_evidence(self._repo, evidence)
        if et in _MISCONCEPTION_TYPES:
            return misconception_updater.apply_misconception_evidence(self._repo, evidence)
        if et in _PROFILE_FACT_TYPES:
            return profile_fact_updater.apply_profile_fact_evidence(self._repo, evidence)
        if et in _GOAL_TYPES:
            return goal_updater.apply_goal_evidence(self._repo, evidence)
        if et in _ABILITY_TYPES:
            from edu_agent.learner_model.updaters import ability as ability_updater

            return ability_updater.apply_ability_evidence(self._repo, evidence)
        return {"operation": "NONE", "reason": f"unhandled {et}", "scope": "course"}

    def _log_change(
        self, event: LearningEvent, change: Dict[str, Any], evidence_ids: List[str]
    ) -> None:
        """change log：保存 before/after；敏感 DELETE 只留最小审计。"""
        from edu_agent.learner_model.change_log import log_change

        op = change.get("operation", "UPDATE")
        sensitive_delete = op == "DELETE" and change.get("entity", "").startswith(
            ("fact:", "memory:")
        )
        log_change(
            self._repo,
            event.user_id,
            entity_type=change.get("entity", "").split(":")[0] or "learner_model",
            entity_id=change.get("entity", ""),
            operation=op,
            course_id=event.course_id,
            reason=change.get("reason", "") or event.event_type,
            evidence_ids=evidence_ids,
            before=None if sensitive_delete else change.get("before"),
            after=None if sensitive_delete else change.get("after"),
        )
        # 版本递增由 apply_event 统一处理（每个 scope 一次）

    def _maybe_snapshot(self, event: LearningEvent, changes: List[Dict[str, Any]]) -> None:
        """按状态版本触发快照（course_state_version % interval == 0）。"""
        if not changes or not event.course_id:
            return
        state = self._repo.get_course_state(event.user_id, event.course_id)
        version = (state or {}).get("state_version", 0)
        if version and version % self._snapshot_interval == 0:
            from edu_agent.learner_model import snapshot as snapshot_mod

            snapshot_mod.take_snapshot(
                self._repo,
                event.user_id,
                event.course_id,
                version,
                self.build_dashboard(event.user_id, event.course_id),
            )

    # ------------------------------------------------------------------
    # 显式操作（USER_EXPLICIT 优先；统一走 mutation pipeline）
    # ------------------------------------------------------------------
    def set_preference(
        self,
        user_id: str,
        preference_key: str,
        score: Optional[float] = None,
        direction: str = "pos",
        course_id: str = "",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"preference_key": preference_key}
        if score is not None:
            payload["score"] = score
        else:
            payload["direction"] = direction
        event = build_event(
            "USER_EXPLICIT_PREFERENCE", user_id=user_id, course_id=course_id, payload=payload
        )
        changes = self.apply_event(event)
        return changes[0] if changes else {"operation": "NONE", "reason": "no change", "scope": "global"}

    def set_profile_fact(
        self, user_id: str, fact_key: str, fact_value: Any, category: str = "background"
    ) -> Dict[str, Any]:
        event = build_event(
            "USER_EXPLICIT_PROFILE_FACT",
            user_id=user_id,
            payload={"fact_key": fact_key, "fact_value": fact_value, "category": category},
        )
        changes = self.apply_event(event)
        return changes[0] if changes else {"operation": "NONE", "reason": "no change", "scope": "global"}

    def delete_profile_fact(self, user_id: str, fact_key: str) -> Dict[str, Any]:
        """用户明确删除事实（真正 DELETE，change log 最小审计）。"""
        result = profile_fact_updater.delete_fact_direct(self._repo, user_id, fact_key)
        if result.get("operation") == "DELETE":
            self._repo.bump_global_version(user_id)
            from edu_agent.learner_model.change_log import log_change

            log_change(
                self._repo,
                user_id,
                entity_type="profile_fact",
                entity_id=f"fact:{fact_key}",
                operation="DELETE",
                reason="user requested",
            )
        return result

    def add_memory(
        self, user_id: str, content: str, course_id: str = "", category: str = "experience"
    ) -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        result = memory_updater.add_memory(self._repo, user_id, content, course_id, category)
        if result.get("operation") != "NONE":
            self._repo.bump_global_version(user_id)
            from edu_agent.learner_model.change_log import log_change

            log_change(
                self._repo,
                user_id,
                entity_type="semantic_memory",
                entity_id=result.get("entity", ""),
                operation=result["operation"],
                course_id=course_id,
                reason=result.get("reason", ""),
                before=result.get("before"),
                after=result.get("after"),
            )
        return result

    def delete_memory(self, user_id: str, memory_id: str) -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        result = memory_updater.delete_memory_direct(self._repo, user_id, memory_id)
        if result.get("operation") == "DELETE":
            self._repo.bump_global_version(user_id)
            from edu_agent.learner_model.change_log import log_change

            log_change(
                self._repo,
                user_id,
                entity_type="semantic_memory",
                entity_id=memory_id,
                operation="DELETE",
                reason="user requested",
            )
        return result

    def upsert_goal(
        self,
        user_id: str,
        goal_id: str,
        course_id: str,
        name: str,
        target: str = "",
        priority: Optional[int] = None,
        target_kcs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not goal_id:
            goal_id = f"GOAL-{user_id}-{course_id}"
        if course_id:
            self.ensure_course(user_id, course_id)
        result = goal_updater.upsert_goal(
            self._repo, user_id, goal_id, course_id, name, target, priority, target_kcs
        )
        if result.get("operation") != "NONE":
            from edu_agent.learner_model.change_log import log_change

            log_change(
                self._repo,
                user_id,
                entity_type="goal",
                entity_id=result.get("entity", ""),
                operation=result["operation"],
                course_id=course_id,
                reason=result.get("reason", ""),
                before=result.get("before"),
                after=result.get("after"),
            )
            self._repo.bump_state_version(user_id, course_id) if course_id else None
        return result

    def set_goal_status(self, user_id: str, goal_id: str, status: str) -> Dict[str, Any]:
        return goal_updater.set_goal_status(self._repo, user_id, goal_id, status)

    def update_goal_progress(self, user_id: str, goal_id: str, progress: float) -> Dict[str, Any]:
        result = goal_updater.update_goal_progress(self._repo, user_id, goal_id, progress)
        if result.get("operation") != "NONE":
            from edu_agent.learner_model.change_log import log_change

            log_change(
                self._repo,
                user_id,
                entity_type="goal",
                entity_id=result.get("entity", ""),
                operation=result["operation"],
                reason=result.get("reason", ""),
                before=result.get("before"),
                after=result.get("after"),
            )
        return result

    def update_course_progress(
        self, user_id: str, course_id: str, progress: float, stage: str = ""
    ) -> None:
        if not course_id:
            return
        existing = self._repo.get_course_state(user_id, course_id) or {}
        self._repo.upsert_course_state(
            {
                "user_id": user_id,
                "course_id": course_id,
                "current_goal_id": existing.get("current_goal_id", ""),
                "progress": max(0.0, min(1.0, progress)),
                "current_stage": stage or existing.get("current_stage", ""),
                "state_version": existing.get("state_version", 1),
                "updated_at": _now_iso(),
            }
        )

    def set_current_goal(self, user_id: str, course_id: str, goal_id: str) -> None:
        if not course_id:
            return
        existing = self._repo.get_course_state(user_id, course_id) or {}
        self._repo.upsert_course_state(
            {
                "user_id": user_id,
                "course_id": course_id,
                "current_goal_id": goal_id,
                "progress": existing.get("progress", 0.0),
                "current_stage": existing.get("current_stage", ""),
                "state_version": existing.get("state_version", 1),
                "updated_at": _now_iso(),
            }
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def build_bundle(
        self,
        user_id: str = DEFAULT_USER_ID,
        course_id: str = DEFAULT_COURSE_ID,
    ) -> LearnerStateBundle:
        """从 SQLite 组装 LearnerStateBundle（含 global/course 双版本）。"""
        self.ensure_course(user_id, course_id)
        learner = self._repo.get_learner(user_id) or {}
        course_row = self._repo.get_course_state(user_id, course_id) or {}

        global_state = GlobalLearnerState(
            profile=Profile(
                user_id=user_id,
                display_name=learner.get("display_name", ""),
                education_level=learner.get("education_level", ""),
                language=learner.get("language", "zh"),
                background=learner.get("background", ""),
            ),
            goals=[Goal(**self._goal_row(g)) for g in self._repo.list_goals(user_id)],
            preferences=self._build_preferences(user_id, course_id),
            semantic_memory=[
                SemanticMemoryItem(content=m.get("content", ""), created_at=m.get("updated_at", ""))
                for m in self._repo.list_global_memories(user_id)
                if m.get("status") in ("active", "candidate")
            ],
        )

        kcs = [
            KnowledgeItem(
                kc_id=k.get("kc_id"),
                name=k.get("kc_name") or k.get("kc_id"),
                mastery=k.get("mastery"),
                confidence=k.get("confidence"),
                status=k.get("status") or "unknown",
                trend=k.get("trend"),
                evidence_count=k.get("evidence_count"),
                last_evidence_at=k.get("last_evidence_at"),
                is_estimated=bool(k.get("is_estimated", 0)),
            )
            for k in self._repo.list_kcs(user_id, course_id)
        ]
        abilities = {
            a["ability_type"]: AbilityItem(
                score=a.get("score"),
                confidence=a.get("confidence"),
                trend=a.get("trend"),
                evidence_count=a.get("evidence_count"),
            )
            for a in self._repo.list_abilities(user_id, course_id)
        }
        misconceptions = [
            Misconception(
                misconception_id=m.get("misconception_id"),
                kc_id=m.get("kc_id"),
                misconception_key=m.get("misconception_key", ""),
                type=m.get("type") or "conceptual_confusion",
                description=m.get("description", ""),
                severity=float(m.get("severity", 0.5)),
                confidence=float(m.get("confidence", 0.3)),
                occurrence_count=int(m.get("occurrence_count", 0)),
                status=m.get("status") or "candidate",
                first_seen_at=m.get("first_seen_at"),
                last_seen_at=m.get("last_seen_at"),
            )
            for m in self._repo.list_misconceptions(user_id, course_id)
            if m.get("status") != "resolved"
        ]

        from edu_agent.learner_model.updaters import behavior as behavior_updater

        course_state = CourseLearnerState(
            schema_version=1,
            user_id=user_id,
            course_id=course_id,
            goal_id=course_row.get("current_goal_id", ""),
            progress=float(course_row.get("progress", 0.0)),
            knowledge=kcs,
            abilities=abilities,
            misconceptions=misconceptions,
            behavior=behavior_updater.aggregate(self._repo, user_id, course_id),
            state_version=course_row.get("state_version"),
            updated_at=course_row.get("updated_at"),
            freshness="fresh",
        )

        active_goal = None
        for g in self._repo.list_goals(user_id, status="active"):
            if g.get("course_id") in ("", course_id):
                active_goal = Goal(**self._goal_row(g))
                break

        return LearnerStateBundle(
            user_id=user_id,
            course_id=course_id,
            global_state=global_state,
            course_state=course_state,
            active_goal=active_goal,
            global_state_version=learner.get("global_state_version"),
            course_state_version=course_row.get("state_version"),
        )

    def _goal_row(self, row: dict) -> dict:
        try:
            target_kcs = json.loads(row.get("target_kcs_json") or "[]")
        except (ValueError, TypeError):
            target_kcs = []
        return {
            "goal_id": row.get("goal_id"),
            "course_id": row.get("course_id", ""),
            "goal_name": row.get("name"),
            "target": row.get("target", ""),
            "priority": row.get("priority", 1),
            "status": row.get("status", "active"),
            "progress": float(row.get("progress", 0.0)),
            "target_kcs": target_kcs,
        }

    def _build_preferences(self, user_id: str, course_id: str = "") -> Preferences:
        rows = self._repo.list_preferences(user_id, course_id)
        mode_effectiveness: Dict[str, ModeScore] = {}
        best_key, best_score = "", 0.0
        for r in rows:
            key = r["preference_key"]
            score = float(r.get("score", 0.5))
            confidence = float(r.get("confidence", 0.0))
            if r.get("status") == "inactive":
                continue
            existing = mode_effectiveness.get(key)
            if existing is None:
                mode_effectiveness[key] = ModeScore(
                    score=score, confidence=confidence,
                    sample_size=int(r.get("evidence_count", 0)),
                )
            else:
                is_course_specific = r.get("course_id") == course_id
                user_explicit_wins = (
                    r.get("course_id") == "" and confidence >= 0.8
                    and confidence > existing.confidence
                )
                if is_course_specific or user_explicit_wins:
                    mode_effectiveness[key] = ModeScore(
                        score=score, confidence=confidence,
                        sample_size=int(r.get("evidence_count", 0)),
                    )
            final = mode_effectiveness[key]
            if final.confidence >= 0.5 and final.score * final.confidence > best_score:
                best_score = final.score * final.confidence
                best_key = key
        return Preferences(
            preferred_mode=best_key,
            mode_effectiveness=mode_effectiveness,
        )

    def build_dashboard(self, user_id: str, course_id: str) -> Dict[str, Any]:
        """完整画像快照（前端展示用）。"""
        bundle = self.build_bundle(user_id, course_id)
        return {
            "user_id": user_id,
            "course_id": course_id,
            "profile": bundle.global_state.profile.model_dump(),
            "facts": self._repo.list_profile_facts(user_id),
            "goals": self._repo.list_goals(user_id),
            "course_state": bundle.course_state.model_dump(),
            "preferences": {
                k: v.model_dump() for k, v in bundle.global_state.preferences.mode_effectiveness.items()
            },
            "semantic_memories": self._repo.list_effective_memories(user_id, course_id),
            "global_state_version": bundle.global_state_version,
            "course_state_version": bundle.course_state_version,
            "updated_at": bundle.course_state.updated_at,
        }

    def get_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        return self._repo.list_changes(user_id, course_id=course_id, limit=limit)

    def get_events(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]:
        return self._repo.list_events(user_id, course_id=course_id, limit=limit)

    def get_evidences(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        return self._repo.list_evidences(user_id, course_id=course_id, limit=limit)

    def record_decision(
        self,
        decision: Dict[str, Any],
        user_id: str,
        course_id: str = "",
        goal_id: str = "",
        session_id: str = "",
        task_type: str = "",
        target_kc: str = "",
        global_state_version: Optional[int] = None,
        course_state_version: Optional[int] = None,
    ) -> str:
        """持久化一次 Adaptive Decision（只在真正执行教学动作时调用，不随 render 调用）。"""
        import uuid

        decision_id = f"DEC-{uuid.uuid4().hex[:12]}"
        reason_codes = (decision or {}).get("reason_codes") or []
        self._repo.insert_decision(
            {
                "decision_id": decision_id,
                "user_id": user_id,
                "course_id": course_id,
                "goal_id": goal_id,
                "session_id": session_id,
                "task_type": task_type,
                "target_kc": target_kc,
                "global_state_version": global_state_version,
                "course_state_version": course_state_version,
                "selected_context_json": json.dumps(
                    (decision or {}).get("selected_context", {}), ensure_ascii=False, default=str
                ),
                "temporal_state_json": json.dumps(
                    (decision or {}).get("temporal_state", {}), ensure_ascii=False, default=str
                ),
                "decision_json": json.dumps(
                    {k: v for k, v in (decision or {}).items() if k not in ("selected_context", "temporal_state", "reason_codes")},
                    ensure_ascii=False, default=str,
                ),
                "reason_codes_json": json.dumps(reason_codes, ensure_ascii=False),
                "policy_version": "rule-v1",
                "created_at": _now_iso(),
            }
        )
        return decision_id


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
