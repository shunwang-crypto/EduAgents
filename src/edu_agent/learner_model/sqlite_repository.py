"""SQLite Learner Model Repository 实现。

事务约定：
- 写方法只准备数据并执行，**不主动 commit**；commit/rollback 由
  `transaction()` 上下文（或独立单写调用）负责。
- `_commit()`：仅在事务外执行时提交（单写原子）；事务内由 owner 统一提交。
- 业务代码通过 service / updaters 访问，禁止直接 SQL。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from edu_agent.learner_model.db import get_connection
from edu_agent.learner_model.repository import LearnerRepository


def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict]:
    return dict(row) if row is not None else None


class SQLiteLearnerRepository(LearnerRepository):
    """SQLite 实现。db_path=None 使用默认 data/learner_model.db。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._conn = get_connection(db_path)
        self._tx_depth = 0

    # ------------------------------------------------------------------
    # 事务控制
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """原子事务：成功 COMMIT，异常 ROLLBACK。支持嵌套（外层负责提交）。"""
        if self._tx_depth > 0:
            yield
            return
        self._tx_depth += 1
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._tx_depth -= 1

    def _commit(self) -> None:
        """事务外单写时立即提交；事务内不提交（由 transaction owner 负责）。"""
        if self._tx_depth == 0:
            self._conn.commit()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _insert_or_update(self, table: str, row: Dict[str, Any], key_cols: List[str]) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        update_set = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key_cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({', '.join(key_cols)}) DO UPDATE SET {update_set}"
        )
        self._conn.execute(sql, row)
        self._commit()

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        return _row_to_dict(self._conn.execute(sql, params).fetchone())

    def _fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # learners
    # ------------------------------------------------------------------
    def ensure_learner(self, user_id: str, display_name: str = "") -> None:
        now = _now_iso()
        row = self.get_learner(user_id)
        if row is None:
            self._insert_or_update(
                "learners",
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "education_level": "",
                    "language": "zh",
                    "background": "",
                    "global_state_version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
                ["user_id"],
            )
        elif display_name and row.get("display_name") != display_name:
            self._conn.execute(
                "UPDATE learners SET display_name=?, updated_at=? WHERE user_id=?",
                (display_name, now, user_id),
            )
            self._commit()

    def get_learner(self, user_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM learners WHERE user_id=?", (user_id,))

    def bump_global_version(self, user_id: str) -> int:
        """全局画像版本 +1（事实/全局偏好/全局记忆），返回新版本。"""
        cur = self._fetchone(
            "SELECT global_state_version FROM learners WHERE user_id=?", (user_id,)
        )
        new_version = (cur["global_state_version"] + 1) if cur else 1
        self._conn.execute(
            "INSERT INTO learners (user_id, global_state_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET global_state_version=?, updated_at=?",
            (user_id, new_version, _now_iso(), _now_iso(), new_version, _now_iso()),
        )
        self._commit()
        return new_version

    # ------------------------------------------------------------------
    # profile facts
    # ------------------------------------------------------------------
    def upsert_profile_fact(self, fact: Dict[str, Any]) -> None:
        existing = self.get_profile_fact(fact.get("user_id", ""), fact.get("fact_key", ""))
        row = {**fact, "fact_id": existing["fact_id"]} if existing else dict(fact)
        self._insert_or_update("learner_profile_facts", row, ["fact_id"])

    def get_profile_fact(self, user_id: str, fact_key: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_profile_facts WHERE user_id=? AND fact_key=?",
            (user_id, fact_key),
        )

    def list_profile_facts(self, user_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_profile_facts WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        )

    def delete_profile_fact(self, user_id: str, fact_id: str) -> None:
        self._conn.execute(
            "DELETE FROM learner_profile_facts WHERE user_id=? AND fact_id=?",
            (user_id, fact_id),
        )
        self._commit()

    # ------------------------------------------------------------------
    # goals（联合主键 user_id + goal_id）
    # ------------------------------------------------------------------
    def upsert_goal(self, goal: Dict[str, Any]) -> None:
        self._insert_or_update("learning_goals", goal, ["user_id", "goal_id"])

    def get_goal(self, user_id: str, goal_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learning_goals WHERE user_id=? AND goal_id=?", (user_id, goal_id)
        )

    def list_goals(self, user_id: str, status: Optional[str] = None) -> List[dict]:
        if status:
            return self._fetchall(
                "SELECT * FROM learning_goals WHERE user_id=? AND status=? ORDER BY priority ASC",
                (user_id, status),
            )
        return self._fetchall(
            "SELECT * FROM learning_goals WHERE user_id=? ORDER BY priority ASC", (user_id,)
        )

    # ------------------------------------------------------------------
    # course states
    # ------------------------------------------------------------------
    def upsert_course_state(self, state: Dict[str, Any]) -> None:
        self._insert_or_update("learner_course_states", state, ["user_id", "course_id"])

    def get_course_state(self, user_id: str, course_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_course_states WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )

    def bump_state_version(self, user_id: str, course_id: str) -> int:
        """课程状态版本 +1，返回新版本号。"""
        cur = self._fetchone(
            "SELECT state_version FROM learner_course_states WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )
        new_version = (cur["state_version"] + 1) if cur else 1
        self._conn.execute(
            "INSERT INTO learner_course_states (user_id, course_id, state_version, progress, current_stage, current_goal_id, updated_at) "
            "VALUES (?, ?, ?, 0.0, '', '', ?) "
            "ON CONFLICT(user_id, course_id) DO UPDATE SET state_version=?, updated_at=?",
            (user_id, course_id, new_version, _now_iso(), new_version, _now_iso()),
        )
        self._commit()
        return new_version

    # ------------------------------------------------------------------
    # kc states
    # ------------------------------------------------------------------
    def upsert_kc(self, kc: Dict[str, Any]) -> None:
        self._insert_or_update("learner_kc_states", kc, ["user_id", "course_id", "kc_id"])

    def get_kc(self, user_id: str, course_id: str, kc_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_kc_states WHERE user_id=? AND course_id=? AND kc_id=?",
            (user_id, course_id, kc_id),
        )

    def list_kcs(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_kc_states WHERE user_id=? AND course_id=? ORDER BY kc_id",
            (user_id, course_id),
        )

    # ------------------------------------------------------------------
    # abilities
    # ------------------------------------------------------------------
    def upsert_ability(self, ability: Dict[str, Any]) -> None:
        self._insert_or_update(
            "learner_abilities", ability, ["user_id", "course_id", "ability_type"]
        )

    def get_ability(self, user_id: str, course_id: str, ability_type: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_abilities WHERE user_id=? AND course_id=? AND ability_type=?",
            (user_id, course_id, ability_type),
        )

    def list_abilities(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_abilities WHERE user_id=? AND course_id=? ORDER BY ability_type",
            (user_id, course_id),
        )

    # ------------------------------------------------------------------
    # preferences
    # ------------------------------------------------------------------
    def upsert_preference(self, pref: Dict[str, Any]) -> None:
        self._insert_or_update(
            "learner_preferences", pref, ["user_id", "course_id", "preference_key"]
        )

    def get_preference(self, user_id: str, preference_key: str, course_id: str = "") -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_preferences WHERE user_id=? AND course_id=? AND preference_key=?",
            (user_id, course_id, preference_key),
        )

    def list_preferences(self, user_id: str, course_id: str = "") -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM learner_preferences WHERE user_id=? AND (course_id=? OR course_id='') "
                "ORDER BY course_id DESC, preference_key",
                (user_id, course_id),
            )
        return self._fetchall(
            "SELECT * FROM learner_preferences WHERE user_id=? ORDER BY course_id DESC, preference_key",
            (user_id,),
        )

    # ------------------------------------------------------------------
    # misconceptions（多实例：user+course+kc+key）
    # ------------------------------------------------------------------
    def upsert_misconception(self, m: Dict[str, Any]) -> None:
        self._insert_or_update("learner_misconceptions", m, ["misconception_id"])

    def get_misconception(self, misconception_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_misconceptions WHERE misconception_id=?", (misconception_id,)
        )

    def find_misconception(
        self, user_id: str, course_id: str, kc_id: str, misconception_key: str = ""
    ) -> Optional[dict]:
        """按 user+course+kc+key 精确匹配（key 空则回退 kc 级）。"""
        if misconception_key:
            return self._fetchone(
                "SELECT * FROM learner_misconceptions WHERE user_id=? AND course_id=? "
                "AND kc_id=? AND misconception_key=?",
                (user_id, course_id, kc_id, misconception_key),
            )
        return self._fetchone(
            "SELECT * FROM learner_misconceptions WHERE user_id=? AND course_id=? "
            "AND kc_id=? AND misconception_key=''",
            (user_id, course_id, kc_id),
        )

    def list_misconceptions(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_misconceptions WHERE user_id=? AND course_id=? "
            "ORDER BY last_seen_at DESC",
            (user_id, course_id),
        )

    # ------------------------------------------------------------------
    # semantic memories（课程隔离）
    # ------------------------------------------------------------------
    def upsert_memory(self, memory: Dict[str, Any]) -> None:
        self._insert_or_update("learner_semantic_memories", memory, ["memory_id"])

    def list_global_memories(self, user_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_semantic_memories WHERE user_id=? AND course_id='' "
            "ORDER BY updated_at DESC",
            (user_id,),
        )

    def list_course_memories(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_semantic_memories WHERE user_id=? AND course_id=? "
            "ORDER BY updated_at DESC",
            (user_id, course_id),
        )

    def list_effective_memories(self, user_id: str, course_id: str) -> List[dict]:
        """当前课程上下文 = 全局记忆 + 本课程记忆（不含其他课程）。"""
        return self.list_global_memories(user_id) + self.list_course_memories(user_id, course_id)

    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]:
        if course_id:
            return self.list_effective_memories(user_id, course_id)
        return self.list_global_memories(user_id)

    def delete_memory(self, user_id: str, memory_id: str) -> None:
        self._conn.execute(
            "DELETE FROM learner_semantic_memories WHERE user_id=? AND memory_id=?",
            (user_id, memory_id),
        )
        self._commit()

    # ------------------------------------------------------------------
    # events（append-only + 幂等）
    # ------------------------------------------------------------------
    def insert_event(self, event: Dict[str, Any]) -> bool:
        """插入事件。event_id 已存在返回 False（幂等），否则 True。"""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO learning_events (event_id, schema_version, event_type, user_id, course_id, "
            "goal_id, kc_id, session_id, timestamp, source, evidence_strength, payload_json, created_at) "
            "VALUES (:event_id, :schema_version, :event_type, :user_id, :course_id, :goal_id, :kc_id, "
            ":session_id, :timestamp, :source, :evidence_strength, :payload_json, :created_at)",
            event,
        )
        self._commit()
        return cur.rowcount > 0

    def event_exists(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM learning_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return row is not None

    def list_events(self, user_id: str, course_id: str = "", limit: int = 200) -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM learning_events WHERE user_id=? AND course_id=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        return self._fetchall(
            "SELECT * FROM learning_events WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        )

    def list_events_since(self, user_id: str, course_id: str, since_iso: str, limit: int = 1000) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learning_events WHERE user_id=? AND course_id=? AND timestamp>=? "
            "ORDER BY timestamp DESC LIMIT ?",
            (user_id, course_id, since_iso, limit),
        )

    def count_events(self, user_id: str, course_id: str = "") -> int:
        if course_id:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM learning_events WHERE user_id=? AND course_id=?",
                (user_id, course_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM learning_events WHERE user_id=?", (user_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # evidences（provenance + 幂等）
    # ------------------------------------------------------------------
    def insert_evidence(self, evidence: Dict[str, Any]) -> bool:
        """插入证据；唯一键 (event_id, entity_type, entity_key, classifier_version) 已存在返回 False。"""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO learner_evidences (evidence_id, event_id, event_type, user_id, "
            "course_id, kc_id, entity_type, entity_key, direction, weight, source, "
            "classifier_version, confidence, meaningful_for_profile, payload_json, created_at) "
            "VALUES (:evidence_id, :event_id, :event_type, :user_id, :course_id, :kc_id, "
            ":entity_type, :entity_key, :direction, :weight, :source, :classifier_version, "
            ":confidence, :meaningful_for_profile, :payload_json, :created_at)",
            evidence,
        )
        self._commit()
        return cur.rowcount > 0

    def evidence_exists(self, event_id: str, entity_type: str, entity_key: str, classifier_version: str = "rule-v1") -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM learner_evidences WHERE event_id=? AND entity_type=? "
            "AND entity_key=? AND classifier_version=?",
            (event_id, entity_type, entity_key, classifier_version),
        ).fetchone()
        return row is not None

    def list_evidences(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM learner_evidences WHERE user_id=? AND course_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        return self._fetchall(
            "SELECT * FROM learner_evidences WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )

    # ------------------------------------------------------------------
    # change log
    # ------------------------------------------------------------------
    def insert_change(self, change: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO profile_change_log (change_id, user_id, course_id, entity_type, entity_id, "
            "operation, before_json, after_json, reason, evidence_ids_json, created_at) "
            "VALUES (:change_id, :user_id, :course_id, :entity_type, :entity_id, :operation, "
            ":before_json, :after_json, :reason, :evidence_ids_json, :created_at)",
            change,
        )
        self._commit()

    def list_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM profile_change_log WHERE user_id=? AND (course_id=? OR course_id='') "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        return self._fetchall(
            "SELECT * FROM profile_change_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------
    def insert_snapshot(self, snapshot: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO learner_state_snapshots (snapshot_id, user_id, course_id, state_version, "
            "snapshot_json, created_at) VALUES (:snapshot_id, :user_id, :course_id, :state_version, "
            ":snapshot_json, :created_at)",
            snapshot,
        )
        self._commit()

    def list_snapshots(self, user_id: str, course_id: str = "", limit: int = 20) -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM learner_state_snapshots WHERE user_id=? AND course_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        return self._fetchall(
            "SELECT * FROM learner_state_snapshots WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )

    # ------------------------------------------------------------------
    # adaptive decisions
    # ------------------------------------------------------------------
    def insert_decision(self, decision: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO adaptive_decisions (decision_id, user_id, course_id, goal_id, session_id, "
            "task_type, target_kc, global_state_version, course_state_version, selected_context_json, "
            "temporal_state_json, decision_json, reason_codes_json, policy_version, created_at) "
            "VALUES (:decision_id, :user_id, :course_id, :goal_id, :session_id, :task_type, :target_kc, "
            ":global_state_version, :course_state_version, :selected_context_json, "
            ":temporal_state_json, :decision_json, :reason_codes_json, :policy_version, :created_at)",
            decision,
        )
        self._commit()

    def list_decisions(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM adaptive_decisions WHERE user_id=? AND course_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        return self._fetchall(
            "SELECT * FROM adaptive_decisions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )

    # ------------------------------------------------------------------
    # domain courses（自定义课程 Domain Model 持久化）
    # ------------------------------------------------------------------
    def upsert_domain_course(self, course: Dict[str, Any]) -> None:
        self._insert_or_update("domain_courses", course, ["course_id"])

    def get_domain_course(self, course_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM domain_courses WHERE course_id=?", (course_id,))

    def list_domain_courses(self) -> List[dict]:
        return self._fetchall("SELECT * FROM domain_courses ORDER BY created_at DESC")

    def upsert_domain_kc(self, kc: Dict[str, Any]) -> None:
        self._insert_or_update("domain_kcs", kc, ["course_id", "kc_id"])

    def list_domain_kcs(self, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM domain_kcs WHERE course_id=? ORDER BY kc_id", (course_id,)
        )

    def upsert_domain_relation(self, rel: Dict[str, Any]) -> None:
        self._insert_or_update(
            "domain_kc_relations", rel, ["course_id", "from_kc", "to_kc", "relation"]
        )

    def list_domain_relations(self, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM domain_kc_relations WHERE course_id=?", (course_id,)
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
