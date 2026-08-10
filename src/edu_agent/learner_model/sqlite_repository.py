"""SQLite Learner Model Repository 实现。

所有写操作在单事务内完成；业务层通过 service/updaters 调用，禁止直接 SQL。
行以 dict 返回（sqlite3.Row → dict）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.db import get_connection
from edu_agent.learner_model.repository import LearnerRepository

# 从表字段 dict 生成插入/更新 SQL 的通用小工具
def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict]:
    return dict(row) if row is not None else None


class SQLiteLearnerRepository(LearnerRepository):
    """SQLite 实现。db_path=None 使用默认 data/learner_model.db。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._conn = get_connection(db_path)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _insert_or_update(self, table: str, row: Dict[str, Any], key_cols: List[str]) -> None:
        """UPSERT：row 含全部要写的字段。key_cols 为联合主键列名。"""
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        update_set = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key_cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({', '.join(key_cols)}) DO UPDATE SET {update_set}"
        )
        self._conn.execute(sql, row)
        self._conn.commit()

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
            self._conn.commit()

    def get_learner(self, user_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM learners WHERE user_id=?", (user_id,))

    # ------------------------------------------------------------------
    # profile facts
    # ------------------------------------------------------------------
    def upsert_profile_fact(self, fact: Dict[str, Any]) -> None:
        # 同 user_id+fact_key 只保留一条：已存在则按该行的 fact_id 更新
        existing = self.get_profile_fact(fact.get("user_id", ""), fact.get("fact_key", ""))
        if existing is not None:
            row = {**fact, "fact_id": existing["fact_id"]}
        else:
            row = dict(fact)
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
        self._conn.commit()

    # ------------------------------------------------------------------
    # goals
    # ------------------------------------------------------------------
    def upsert_goal(self, goal: Dict[str, Any]) -> None:
        self._insert_or_update("learning_goals", goal, ["goal_id"])

    def get_goal(self, goal_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM learning_goals WHERE goal_id=?", (goal_id,))

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
        """状态版本 +1，返回新版本号。"""
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
        self._conn.commit()
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
            # 课程偏好 + 跨课程偏好
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
    # misconceptions
    # ------------------------------------------------------------------
    def upsert_misconception(self, m: Dict[str, Any]) -> None:
        self._insert_or_update("learner_misconceptions", m, ["misconception_id"])

    def get_misconception(self, misconception_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_misconceptions WHERE misconception_id=?", (misconception_id,)
        )

    def list_misconceptions(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_misconceptions WHERE user_id=? AND course_id=? "
            "ORDER BY last_seen_at DESC",
            (user_id, course_id),
        )

    # ------------------------------------------------------------------
    # semantic memories
    # ------------------------------------------------------------------
    def upsert_memory(self, memory: Dict[str, Any]) -> None:
        self._insert_or_update("learner_semantic_memories", memory, ["memory_id"])

    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]:
        if course_id:
            return self._fetchall(
                "SELECT * FROM learner_semantic_memories WHERE user_id=? AND (course_id=? OR course_id='') "
                "ORDER BY updated_at DESC",
                (user_id, course_id),
            )
        return self._fetchall(
            "SELECT * FROM learner_semantic_memories WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        )

    def delete_memory(self, user_id: str, memory_id: str) -> None:
        self._conn.execute(
            "DELETE FROM learner_semantic_memories WHERE user_id=? AND memory_id=?",
            (user_id, memory_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # events (append-only)
    # ------------------------------------------------------------------
    def insert_event(self, event: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO learning_events (event_id, schema_version, event_type, user_id, course_id, "
            "goal_id, kc_id, session_id, timestamp, source, evidence_strength, payload_json, created_at) "
            "VALUES (:event_id, :schema_version, :event_type, :user_id, :course_id, :goal_id, :kc_id, "
            ":session_id, :timestamp, :source, :evidence_strength, :payload_json, :created_at)",
            event,
        )
        self._conn.commit()

    def list_events(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]:
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
        self._conn.commit()

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
        self._conn.commit()

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


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
