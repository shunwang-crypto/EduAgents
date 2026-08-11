"""SQLite Learner Model Repository 实现（范围收缩版）。

- 写方法不主动 commit；由 `transaction()` 上下文统一 COMMIT/ROLLBACK。
- 保留：learners/facts/goals/course_states/kc_states/preferences/memories/events/change_log
- 新增：chat_conversations/chat_messages/study_plans/plan_steps/domain_*
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from edu_agent.learner_model.db import get_connection
from edu_agent.learner_model.repository import LearnerRepository


def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict]:
    return dict(row) if row is not None else None


class SQLiteLearnerRepository(LearnerRepository):
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        # 每线程一条连接（thread-local）：FastAPI 同步路由在线程池执行，
        # 共享单例连接会被多线程同时使用而损坏；连接跨线程复用同样非法。
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = get_connection(self._db_path)
            self._local.conn = conn
            if not hasattr(self._local, "tx_depth"):
                self._local.tx_depth = 0
        return conn

    @property
    def _tx_depth(self) -> int:
        return getattr(self._local, "tx_depth", 0)

    @_tx_depth.setter
    def _tx_depth(self, value: int) -> None:
        self._local.tx_depth = value

    def close(self) -> None:
        """关闭当前线程持有的连接（用于显式生命周期管理）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._local.conn = None

    # ------------------------------------------------------------------
    # 事务
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._tx_depth > 0:
            yield
            return
        self._tx_depth += 1
        try:
            yield
            self._conn().commit()
        except Exception:
            self._conn().rollback()
            raise
        finally:
            self._tx_depth -= 1

    def _commit(self) -> None:
        if self._tx_depth == 0:
            self._conn().commit()

    def _insert_or_update(self, table: str, row: Dict[str, Any], key_cols: List[str]) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        update_set = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key_cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({', '.join(key_cols)}) DO UPDATE SET {update_set}"
        )
        self._conn().execute(sql, row)
        self._commit()

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        return _row_to_dict(self._conn().execute(sql, params).fetchone())

    def _fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        return [dict(r) for r in self._conn().execute(sql, params).fetchall()]

    # ---- learners ---------------------------------------------------------
    def ensure_learner(self, user_id: str, display_name: str = "") -> None:
        now = _now_iso()
        row = self.get_learner(user_id)
        if row is None:
            self._insert_or_update(
                "learners",
                {"user_id": user_id, "display_name": display_name, "education_level": "",
                 "language": "zh", "background": "", "global_state_version": 1,
                 "created_at": now, "updated_at": now},
                ["user_id"],
            )
        elif display_name and row.get("display_name") != display_name:
            self._conn().execute(
                "UPDATE learners SET display_name=?, updated_at=? WHERE user_id=?",
                (display_name, now, user_id),
            )
            self._commit()

    def get_learner(self, user_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM learners WHERE user_id=?", (user_id,))

    def bump_global_version(self, user_id: str) -> int:
        cur = self._fetchone("SELECT global_state_version FROM learners WHERE user_id=?", (user_id,))
        new_version = (cur["global_state_version"] + 1) if cur else 1
        self._conn().execute(
            "INSERT INTO learners (user_id, global_state_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET global_state_version=?, updated_at=?",
            (user_id, new_version, _now_iso(), _now_iso(), new_version, _now_iso()),
        )
        self._commit()
        return new_version

    # ---- profile facts ----------------------------------------------------
    def upsert_profile_fact(self, fact: Dict[str, Any]) -> None:
        existing = self.get_profile_fact(fact.get("user_id", ""), fact.get("fact_key", ""))
        row = {**fact, "fact_id": existing["fact_id"]} if existing else dict(fact)
        self._insert_or_update("learner_profile_facts", row, ["fact_id"])

    def get_profile_fact(self, user_id: str, fact_key: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_profile_facts WHERE user_id=? AND fact_key=?", (user_id, fact_key)
        )

    def list_profile_facts(self, user_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM learner_profile_facts WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        )

    def delete_profile_fact(self, user_id: str, fact_id: str) -> None:
        self._conn().execute(
            "DELETE FROM learner_profile_facts WHERE user_id=? AND fact_id=?", (user_id, fact_id)
        )
        self._commit()

    # ---- goals ------------------------------------------------------------
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

    # ---- course states ----------------------------------------------------
    def upsert_course_state(self, state: Dict[str, Any]) -> None:
        self._insert_or_update("learner_course_states", state, ["user_id", "course_id"])

    def get_course_state(self, user_id: str, course_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_course_states WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )

    def bump_state_version(self, user_id: str, course_id: str) -> int:
        cur = self._fetchone(
            "SELECT state_version FROM learner_course_states WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )
        new_version = (cur["state_version"] + 1) if cur else 1
        self._conn().execute(
            "INSERT INTO learner_course_states (user_id, course_id, state_version, progress, current_stage, current_goal_id, updated_at) "
            "VALUES (?, ?, ?, 0.0, '', '', ?) ON CONFLICT(user_id, course_id) "
            "DO UPDATE SET state_version=?, updated_at=?",
            (user_id, course_id, new_version, _now_iso(), new_version, _now_iso()),
        )
        self._commit()
        return new_version

    # ---- kc states --------------------------------------------------------
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

    # ---- preferences ------------------------------------------------------
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

    # ---- semantic memories ------------------------------------------------
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
        return self.list_global_memories(user_id) + self.list_course_memories(user_id, course_id)

    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]:
        if course_id:
            return self.list_effective_memories(user_id, course_id)
        return self.list_global_memories(user_id)

    def delete_memory(self, user_id: str, memory_id: str) -> None:
        self._conn().execute(
            "DELETE FROM learner_semantic_memories WHERE user_id=? AND memory_id=?",
            (user_id, memory_id),
        )
        self._commit()

    # ---- events -----------------------------------------------------------
    def insert_event(self, event: Dict[str, Any]) -> bool:
        cur = self._conn().execute(
            "INSERT OR IGNORE INTO learning_events (event_id, schema_version, event_type, user_id, course_id, "
            "goal_id, kc_id, session_id, timestamp, source, evidence_strength, payload_json, created_at) "
            "VALUES (:event_id, :schema_version, :event_type, :user_id, :course_id, :goal_id, :kc_id, "
            ":session_id, :timestamp, :source, :evidence_strength, :payload_json, :created_at)",
            event,
        )
        self._commit()
        return cur.rowcount > 0

    def event_exists(self, event_id: str) -> bool:
        row = self._conn().execute("SELECT 1 FROM learning_events WHERE event_id=?", (event_id,)).fetchone()
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

    def count_events(self, user_id: str, course_id: str = "") -> int:
        if course_id:
            row = self._conn().execute(
                "SELECT COUNT(*) AS n FROM learning_events WHERE user_id=? AND course_id=?",
                (user_id, course_id),
            ).fetchone()
        else:
            row = self._conn().execute(
                "SELECT COUNT(*) AS n FROM learning_events WHERE user_id=?", (user_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    # ---- change log -------------------------------------------------------
    def insert_change(self, change: Dict[str, Any]) -> None:
        self._conn().execute(
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

    # ---- chat -------------------------------------------------------------
    def upsert_conversation(self, conv: Dict[str, Any]) -> None:
        self._insert_or_update("chat_conversations", conv, ["conversation_id"])

    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM chat_conversations WHERE conversation_id=?", (conversation_id,)
        )

    def get_course_conversation(self, user_id: str, course_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM chat_conversations WHERE user_id=? AND course_id=? "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, course_id),
        )

    def insert_message(self, msg: Dict[str, Any]) -> None:
        self._conn().execute(
            "INSERT INTO chat_messages (message_id, conversation_id, role, content, created_at, metadata_json) "
            "VALUES (:message_id, :conversation_id, :role, :content, :created_at, :metadata_json)",
            msg,
        )
        self._conn().execute(
            "UPDATE chat_conversations SET updated_at=? WHERE conversation_id=?",
            (msg["created_at"], msg["conversation_id"]),
        )
        self._commit()

    def list_messages(self, conversation_id: str, limit: int = 100) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
            (conversation_id, limit),
        )

    # ---- study plans ------------------------------------------------------
    def upsert_plan(self, plan: Dict[str, Any]) -> None:
        self._insert_or_update("study_plans", plan, ["plan_id"])

    def get_plan(self, user_id: str, course_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM study_plans WHERE user_id=? AND course_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id, course_id),
        )

    def upsert_plan_step(self, step: Dict[str, Any]) -> None:
        # step_id 是 PRIMARY KEY；(plan_id, seq) 另有 UNIQUE 约束
        self._insert_or_update("plan_steps", step, ["step_id"])

    def list_plan_steps(self, plan_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM plan_steps WHERE plan_id=? ORDER BY seq ASC", (plan_id,)
        )

    def get_plan_step(self, plan_id: str, step_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM plan_steps WHERE plan_id=? AND step_id=?", (plan_id, step_id)
        )

    def update_plan_progress(self, plan_id: str, progress: float) -> None:
        self._conn().execute(
            "UPDATE study_plans SET progress=?, updated_at=? WHERE plan_id=?",
            (progress, _now_iso(), plan_id),
        )
        self._commit()

    def delete_plan(self, plan_id: str) -> None:
        """删除计划及其全部步骤（re-generate 替换旧 current plan 用，事务内调用）。"""
        self._conn().execute("DELETE FROM plan_steps WHERE plan_id=?", (plan_id,))
        self._conn().execute("DELETE FROM study_plans WHERE plan_id=?", (plan_id,))
        self._commit()

    def get_plan_step_by_id(self, user_id: str, course_id: str, step_id: str) -> Optional[dict]:
        """按 step_id 跨 plan 定位，并校验属于 user+course（Chat plan_step context 用）。"""
        return self._fetchone(
            "SELECT ps.* FROM plan_steps ps "
            "JOIN study_plans p ON p.plan_id = ps.plan_id "
            "WHERE ps.step_id=? AND p.user_id=? AND p.course_id=?",
            (step_id, user_id, course_id),
        )

    # ---- domain courses ---------------------------------------------------
    def upsert_domain_course(self, course: Dict[str, Any]) -> None:
        self._insert_or_update("domain_courses", course, ["course_id"])

    def get_domain_course(self, course_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM domain_courses WHERE course_id=?", (course_id,))

    def list_domain_courses(self) -> List[dict]:
        return self._fetchall("SELECT * FROM domain_courses ORDER BY created_at DESC")

    def delete_domain_course(self, course_id: str) -> None:
        self._conn().execute("DELETE FROM domain_courses WHERE course_id=?", (course_id,))
        self._conn().execute("DELETE FROM domain_kcs WHERE course_id=?", (course_id,))
        self._conn().execute("DELETE FROM domain_kc_relations WHERE course_id=?", (course_id,))
        self._commit()

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
        return self._fetchall("SELECT * FROM domain_kc_relations WHERE course_id=?", (course_id,))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
