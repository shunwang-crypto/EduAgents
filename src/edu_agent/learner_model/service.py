"""LearnerModelService：面向业务的高层门面。

职责：
- ensure_learner / 显式画像操作（fact/memory/preference/goal）
- record_event + apply_event：写事件 → 提取证据 → 各 Updater 更新画像 → change log → 版本递增
- build_bundle：从 SQLite 组装 LearnerStateBundle（供 adaptive 层消费）

业务代码只允许通过本 Service 访问 Learner Model。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from edu_agent.config.settings import get_settings
from edu_agent.learner_model.change_log import log_change
from edu_agent.learner_model.evidence.extractor import (
    build_event,
    extract_evidence,
    llm_inference_hint,
)
from edu_agent.learner_model.evidence.schemas import LearningEvent, StructuredEvidence
from edu_agent.learner_model.repository import LearnerRepository
from edu_agent.learner_model.schemas import (
    AbilityItem,
    BehaviorState,
    CourseLearnerState,
    GlobalLearnerState,
    Goal,
    KnowledgeItem,
    LearnerStateBundle,
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

# entity_type → updater
_KNOWLEDGE_TYPES = {"knowledge"}
_PREFERENCE_TYPES = {"preference"}
_MISCONCEPTION_TYPES = {"misconception"}
_PROFILE_FACT_TYPES = {"profile_fact"}
_GOAL_TYPES = {"goal"}
_ABILITY_TYPES = {"ability"}


class LearnerModelService:
    """本地 Dynamic Learner Model 唯一入口。"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        repo: Optional[LearnerRepository] = None,
    ) -> None:
        settings = get_settings()
        self._repo = repo or SQLiteLearnerRepository(db_path or settings.learner_model_db_path)
        self._llm_inference = settings.learner_model_llm_inference_enabled
        self._snapshot_interval = settings.learner_model_snapshot_interval

    @property
    def repo(self) -> LearnerRepository:
        return self._repo

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def ensure_learner(self, user_id: str = DEFAULT_USER_ID, display_name: str = "") -> None:
        self._repo.ensure_learner(user_id, display_name)

    def ensure_course(self, user_id: str = DEFAULT_USER_ID, course_id: str = DEFAULT_COURSE_ID) -> None:
        """首次访问课程时建立 course state（无编造数据）。"""
        self.ensure_learner(user_id)
        existing = self._repo.get_course_state(user_id, course_id)
        if existing is None:
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
    # Event 记录与画像更新（闭环核心）
    # ------------------------------------------------------------------
    def record_event(self, event: LearningEvent) -> str:
        """写一条 Event（append-only，返回 event_id）。"""
        if not event.event_id:
            event.event_id = f"EV-{_now_iso().replace(':', '').replace('.', '').replace('-', '')}"
        if not event.timestamp:
            event.timestamp = _now_iso()
        self._repo.insert_event(
            {
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
        )
        return event.event_id

    def apply_event(self, event: LearningEvent) -> List[Dict[str, Any]]:
        """记录事件并更新画像。返回产生的变更列表（供前端展示）。"""
        self.ensure_course(event.user_id, event.course_id)
        self.record_event(event)

        evidences = extract_evidence(event)
        if self._llm_inference:
            evidences += llm_inference_hint(event, use_llm=True)

        changes: List[Dict[str, Any]] = []
        evidence_ids: List[str] = []
        for evidence in evidences:
            evidence_ids.append(evidence.evidence_id)
            change = self._apply_evidence(evidence)
            if change.get("operation") != "NONE":
                changes.append(change)
                self._log(change, event, evidence)

        # 画像版本递增（有实际变更时）
        if changes:
            version = self._repo.bump_state_version(event.user_id, event.course_id)
            from edu_agent.learner_model import snapshot as snapshot_mod

            snapshot_mod.maybe_snapshot(
                self._repo,
                event.user_id,
                event.course_id,
                version,
                self.build_dashboard(event.user_id, event.course_id),
                interval=self._snapshot_interval,
            )
        return changes

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
        return {"operation": "NONE", "reason": f"unhandled {et}"}

    def _log(
        self, change: Dict[str, Any], event: LearningEvent, evidence: StructuredEvidence
    ) -> None:
        log_change(
            self._repo,
            event.user_id,
            entity_type=change.get("entity", "").split(":")[0] or "learner_model",
            entity_id=change.get("entity", ""),
            operation=change.get("operation", "UPDATE"),
            course_id=event.course_id,
            reason=change.get("reason", "") or event.event_type,
            evidence_ids=[evidence.evidence_id],
        )

    # ------------------------------------------------------------------
    # 用户显式操作（USER_EXPLICIT 优先）
    # ------------------------------------------------------------------
    def set_preference(
        self,
        user_id: str,
        preference_key: str,
        score: Optional[float] = None,
        direction: str = "pos",
        course_id: str = "",
    ) -> Dict[str, Any]:
        """用户明确声明偏好（强证据，覆盖旧推断）。"""
        payload: Dict[str, Any] = {"preference_key": preference_key}
        if score is not None:
            payload["score"] = score
        else:
            payload["direction"] = direction
        event = build_event(
            "USER_EXPLICIT_PREFERENCE",
            user_id=user_id,
            course_id=course_id,
            payload=payload,
        )
        changes = self.apply_event(event)
        return changes[0] if changes else {"operation": "NONE", "reason": "no change"}

    def set_profile_fact(
        self,
        user_id: str,
        fact_key: str,
        fact_value: Any,
        category: str = "background",
    ) -> Dict[str, Any]:
        """用户明确声明背景事实。"""
        event = build_event(
            "USER_EXPLICIT_PROFILE_FACT",
            user_id=user_id,
            payload={"fact_key": fact_key, "fact_value": fact_value, "category": category},
        )
        changes = self.apply_event(event)
        return changes[0] if changes else {"operation": "NONE", "reason": "no change"}

    def delete_profile_fact(self, user_id: str, fact_key: str) -> Dict[str, Any]:
        """用户明确删除事实（真正 DELETE，change log 只留最小审计）。"""
        result = profile_fact_updater.delete_fact_direct(self._repo, user_id, fact_key)
        if result.get("operation") == "DELETE":
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
        self,
        user_id: str,
        content: str,
        course_id: str = "",
        category: str = "experience",
    ) -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        return memory_updater.add_memory(self._repo, user_id, content, course_id, category)

    def delete_memory(self, user_id: str, memory_id: str) -> Dict[str, Any]:
        from edu_agent.learner_model.updaters import semantic_memory as memory_updater

        result = memory_updater.delete_memory_direct(self._repo, user_id, memory_id)
        if result.get("operation") == "DELETE":
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
        priority: int = 1,
        target_kcs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        result = goal_updater.upsert_goal(
            self._repo, user_id, goal_id, course_id, name, target, priority, target_kcs
        )
        if result.get("operation") != "NONE":
            log_change(
                self._repo,
                user_id,
                entity_type="goal",
                entity_id=f"goal:{goal_id}",
                operation=result["operation"],
                course_id=course_id,
                reason=result.get("reason", ""),
            )
        return result

    def set_goal_status(self, goal_id: str, status: str, user_id: str = "") -> Dict[str, Any]:
        return goal_updater.set_goal_status(self._repo, goal_id, status)

    def update_goal_progress(self, goal_id: str, progress: float) -> Dict[str, Any]:
        return goal_updater.update_goal_progress(self._repo, goal_id, progress)

    def update_course_progress(
        self, user_id: str, course_id: str, progress: float, stage: str = ""
    ) -> None:
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

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def build_bundle(
        self, user_id: str = DEFAULT_USER_ID, course_id: str = DEFAULT_COURSE_ID
    ) -> LearnerStateBundle:
        """从 SQLite 组装 LearnerStateBundle（adaptive 层直接消费）。"""
        self.ensure_course(user_id, course_id)
        learner = self._repo.get_learner(user_id) or {}
        course_row = self._repo.get_course_state(user_id, course_id) or {}

        # Global
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
                for m in self._repo.list_memories(user_id, "")
                if m.get("status") in ("active", "candidate")
            ],
        )

        # Course
        kcs = [
            KnowledgeItem(
                kc_id=k.get("kc_id"),
                name=k.get("kc_name") or k.get("kc_id"),
                mastery=float(k.get("mastery", 0.0)),
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
                score=float(a.get("score", 0.0)),
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
        # 课程级偏好与跨课程偏好合并：
        # - 课程级优先（更贴合当前课程）；
        # - 但跨课程「用户显式声明」（高置信）不被课程级弱推断覆盖。
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
            "semantic_memories": self._repo.list_memories(user_id, ""),
            "state_version": bundle.course_state.state_version,
            "updated_at": bundle.course_state.updated_at,
        }

    def get_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        return self._repo.list_changes(user_id, course_id=course_id, limit=limit)

    def get_events(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]:
        return self._repo.list_events(user_id, course_id=course_id, limit=limit)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
