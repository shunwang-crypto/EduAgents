"""SQLite Learner Model Repository 实现（范围收缩版）。

- 写方法不主动 commit；由 `transaction()` 上下文统一 COMMIT/ROLLBACK。
- 保留：learners/facts/goals/course_states/kc_states/preferences/memories/events/change_log
- 新增：chat_conversations/chat_messages/study_plans/plan_steps/domain_*
"""

from __future__ import annotations

import json
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
                 "language": "zh", "background": "",
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

    # ---- user courses -----------------------------------------------------
    def upsert_user_course(self, course: Dict[str, Any]) -> None:
        self._insert_or_update("user_courses", course, ["user_id", "course_id"])

    def update_user_course_if_unchanged(self, user_id: str, course_id: str,
                                        expected_updated_at: str, fields: Dict[str, Any]) -> bool:
        if not fields:
            return self.get_user_course(user_id, course_id) is not None
        values = dict(fields)
        values["updated_at"] = fields.get("updated_at") or _now_iso()
        assignments = ", ".join(f"{k}=?" for k in values)
        params = tuple(values.values()) + (user_id, course_id, expected_updated_at)
        cur = self._conn().execute(
            f"UPDATE user_courses SET {assignments} WHERE user_id=? AND course_id=? AND updated_at=?",
            params,
        )
        self._commit()
        return cur.rowcount == 1

    def get_user_course(self, user_id: str, course_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM user_courses WHERE user_id=? AND course_id=?", (user_id, course_id)
        )

    def list_user_courses(self, user_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM user_courses WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        )

    def delete_user_course(self, user_id: str, course_id: str) -> None:
        self._conn().execute(
            "DELETE FROM user_courses WHERE user_id=? AND course_id=?", (user_id, course_id)
        )
        self._commit()

    def delete_user_course_data(self, user_id: str, course_id: str) -> None:
        """删除当前用户在当前课程的全部 user-scoped 数据（单事务，共享 Domain 不碰）。"""
        self._conn().execute("DELETE FROM user_courses WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute("DELETE FROM learner_course_states WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute("DELETE FROM learning_goals WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute(
            "DELETE FROM plan_steps WHERE plan_id IN (SELECT plan_id FROM study_plans WHERE user_id=? AND course_id=?)",
            (user_id, course_id),
        )
        self._conn().execute("DELETE FROM study_plans WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute(
            "DELETE FROM chat_messages WHERE conversation_id IN "
            "(SELECT conversation_id FROM chat_conversations WHERE user_id=? AND course_id=?)",
            (user_id, course_id),
        )
        self._conn().execute("DELETE FROM chat_conversations WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute("DELETE FROM learner_kc_states WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute("DELETE FROM learner_preferences WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute("DELETE FROM learner_semantic_memories WHERE user_id=? AND course_id=?", (user_id, course_id))
        self._conn().execute(
            "DELETE FROM profile_change_log WHERE user_id=? AND course_id=?", (user_id, course_id)
        )
        # 课程级背景事实（background:{course_id}）属于本课程的 scoped key，
        # 删除课程时必须一并清除；绝不动 global skills / global preferences /
        # global facts / semantic global memory / 其他 course memories / 其他 course goals。
        self._conn().execute(
            "DELETE FROM learner_profile_facts WHERE user_id=? AND fact_key=?",
            (user_id, f"background:{course_id}"),
        )
        # 课程资料（user-scoped）：删除课程时一并清除元数据
        self._conn().execute(
            "DELETE FROM course_sources WHERE user_id=? AND course_id=?", (user_id, course_id)
        )
        # 动态 canonical KCGraph：删除课程时一并清除，避免重建同名课程时复活旧 graph
        self._conn().execute(
            "DELETE FROM course_kc_graph WHERE user_id=? AND course_id=?", (user_id, course_id)
        )
        # 结构化讲解缓存：删除课程时一并清除
        self._conn().execute(
            "DELETE FROM step_explanations WHERE user_id=? AND course_id=?", (user_id, course_id)
        )
        self._commit()

    # ---- course categories（纯组织层，user scoped；零 adaptive 数据）--------
    def create_course_category(self, user_id: str, category_id: str, name: str) -> None:
        now = _now_iso()
        self._insert_or_update(
            "course_categories",
            {"category_id": category_id, "user_id": user_id, "name": name,
             "created_at": now, "updated_at": now},
            ["category_id"],
        )

    def list_course_categories(self, user_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM course_categories WHERE user_id=? ORDER BY name COLLATE NOCASE",
            (user_id,),
        )

    def get_course_category(self, user_id: str, category_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM course_categories WHERE user_id=? AND category_id=?",
            (user_id, category_id),
        )

    def rename_course_category(self, user_id: str, category_id: str, name: str) -> None:
        self._conn().execute(
            "UPDATE course_categories SET name=?, updated_at=? WHERE user_id=? AND category_id=?",
            (name, _now_iso(), user_id, category_id),
        )
        self._commit()

    def delete_course_category(self, user_id: str, category_id: str) -> None:
        """原子删除分类：分类下课程移到未分类（category_id=NULL），绝不删除课程/
        Plan/Chat/Sources/Learner State。"""
        with self.transaction():
            self._conn().execute(
                "UPDATE user_courses SET category_id=NULL WHERE user_id=? AND category_id=?",
                (user_id, category_id),
            )
            self._conn().execute(
                "DELETE FROM course_categories WHERE user_id=? AND category_id=?",
                (user_id, category_id),
            )

    def set_course_category(self, user_id: str, course_id: str,
                            category_id: Optional[str]) -> None:
        """把课程归入分类；None = 移到未分类（category_id=NULL）。"""
        if category_id is None:
            self._conn().execute(
                "UPDATE user_courses SET category_id=NULL WHERE user_id=? AND course_id=?",
                (user_id, course_id),
            )
        else:
            self._conn().execute(
                "UPDATE user_courses SET category_id=? WHERE user_id=? AND course_id=?",
                (category_id, user_id, course_id),
            )
        self._commit()

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

    def update_goal_if_unchanged(self, user_id: str, goal_id: str,
                                 expected_updated_at: str, fields: Dict[str, Any]) -> bool:
        if not fields:
            return self.get_goal(user_id, goal_id) is not None
        assignments = ", ".join(f"{k}=?" for k in fields)
        cur = self._conn().execute(
            f"UPDATE learning_goals SET {assignments} WHERE user_id=? AND goal_id=? AND updated_at=?",
            tuple(fields.values()) + (user_id, goal_id, expected_updated_at),
        )
        self._commit()
        return cur.rowcount == 1

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
        """有效记忆：当前课程优先于 global（course memories 不被 global 挤掉）。"""
        return self.list_course_memories(user_id, course_id) + self.list_global_memories(user_id)

    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]:
        if course_id:
            return self.list_effective_memories(user_id, course_id)
        return self.list_global_memories(user_id)

    def get_memory(self, user_id: str, memory_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM learner_semantic_memories WHERE user_id=? AND memory_id=?",
            (user_id, memory_id),
        )

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
        """返回事件列表，并把 ``payload_json`` 反序列化为 ``payload`` dict。

        事件 payload 以 JSON 文本存于 ``payload_json`` 列；消费者（snapshot /
        turn context / recent_error）依赖 ``event["payload"]`` dict 结构。
        """
        if course_id:
            rows = self._fetchall(
                "SELECT * FROM learning_events WHERE user_id=? AND course_id=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (user_id, course_id, limit),
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM learning_events WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            )
        return [self._deserialize_event(r) for r in rows]

    @staticmethod
    def _deserialize_event(row: dict) -> dict:
        ev = dict(row)
        payload = ev.get("payload_json")
        if isinstance(payload, str):
            try:
                ev["payload"] = json.loads(payload)
            except (ValueError, TypeError):
                ev["payload"] = {}
        else:
            ev["payload"] = payload or {}
        return ev

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

    def get_conversation_for_user(self, user_id: str, conversation_id: str) -> Optional[dict]:
        """按 conversation_id 定位，并校验属于该 user（ownership-safe）。"""
        return self._fetchone(
            "SELECT * FROM chat_conversations WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
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
        """全部消息（旧→新，最多 limit 条）。"""
        return self._fetchall(
            "SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
            (conversation_id, limit),
        )

    def list_recent_messages(self, conversation_id: str, limit: int = 8) -> List[dict]:
        """最近 N 条消息（chronological 旧→新）。

        实现：ORDER BY created_at DESC LIMIT N 取最新，再 reverse。
        切勿用 ASC LIMIT（那是最早 N 条）。
        """
        rows = self._fetchall(
            "SELECT * FROM chat_messages WHERE conversation_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        )
        return list(reversed(rows))

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

    def update_plan_step_lesson(self, step_id: str, lesson_markdown: str,
                                lesson_generated_at: str, updated_at: str) -> bool:
        cur = self._conn().execute(
            "UPDATE plan_steps SET lesson_markdown=?, lesson_generated_at=?, updated_at=? WHERE step_id=?",
            (lesson_markdown, lesson_generated_at, updated_at, step_id),
        )
        self._commit()
        return cur.rowcount == 1

    def list_plan_steps(self, plan_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM plan_steps WHERE plan_id=? ORDER BY seq ASC", (plan_id,)
        )

    def get_plan_step(self, plan_id: str, step_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM plan_steps WHERE plan_id=? AND step_id=?", (plan_id, step_id)
        )

    def update_plan_brief(self, plan_id: str, plan_brief_json: str) -> None:
        self._conn().execute(
            "UPDATE study_plans SET plan_brief_json=?, updated_at=? WHERE plan_id=?",
            (plan_brief_json, _now_iso(), plan_id),
        )
        self._commit()

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

    # ---- Structured Explanation（step_explanations）-------------------------
    def upsert_step_explanation(self, row: Dict[str, Any]) -> None:
        # step_id is the actual uniqueness key. Explanation IDs are generated
        # per request, so upserting by explanation_id races when the page makes
        # concurrent GET requests for the same step.
        self._insert_or_update("step_explanations", row, ["step_id"])

    def get_step_explanation(self, user_id: str, course_id: str, step_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM step_explanations WHERE step_id=? AND user_id=? AND course_id=?",
            (step_id, user_id, course_id),
        )

    def delete_step_explanations(self, user_id: str, course_id: str) -> None:
        self._conn().execute(
            "DELETE FROM step_explanations WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )

    def get_plan_step_by_id(self, user_id: str, course_id: str, step_id: str) -> Optional[dict]:
        """按 step_id 跨 plan 定位，并校验属于 user+course（Chat plan_step context 用）。"""
        return self._fetchone(
            "SELECT ps.* FROM plan_steps ps "
            "JOIN study_plans p ON p.plan_id = ps.plan_id "
            "WHERE ps.step_id=? AND p.user_id=? AND p.course_id=?",
            (step_id, user_id, course_id),
        )

    # ---- 动态 KCGraph 快照（canonical Knowledge Graph）-------------------
    def upsert_course_kc_graph(self, row: Dict[str, Any]) -> None:
        """持久化某 (user_id, course_id) 的动态 canonical KCGraph 快照。

        row 字段：user_id, course_id, graph_source, graph_version,
        generated_at, updated_at, nodes_json, edges_json。
        与 study_plan 在同一事务内写入，保证二者版本一致（原子性）。
        """
        self._insert_or_update("course_kc_graph", row, ["user_id", "course_id"])

    def get_course_kc_graph(self, user_id: str, course_id: str) -> Optional[dict]:
        """读取动态 KCGraph 快照；不存在返回 None（调用方应回退到 built-in）。"""
        return self._fetchone(
            "SELECT * FROM course_kc_graph WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )

    def delete_course_kc_graph(self, user_id: str, course_id: str) -> None:
        """删除某 (user_id, course_id) 的动态 KCGraph 快照（课程删除时调用）。"""
        self._conn().execute(
            "DELETE FROM course_kc_graph WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )
        self._commit()

    # ---- conversations（recent list + 标题）------------------------------
    def list_conversations(self, user_id: str, course_id: str, limit: int = 6) -> List[dict]:
        """最近对话：按 updated_at DESC；排除无用户消息的空对话；严格 user+course 隔离。

        course_id 为空串 = General Chat；非空 = 该 Course 的对话。
        title 用 COALESCE：优先真实 title，缺失时 fallback 到首条 user 消息
        （兼容旧开发数据 title=NULL 但 messages 非空的情况，无需 migration）。
        最终 normalize/truncate 在 ChatService 做。
        """
        return self._fetchall(
            "SELECT c.conversation_id, c.user_id, c.course_id, "
            "COALESCE(NULLIF(c.title, ''), ("
            "  SELECT m.content FROM chat_messages m "
            "  WHERE m.conversation_id = c.conversation_id AND m.role='user' "
            "  ORDER BY m.created_at ASC LIMIT 1"
            ")) AS title, c.updated_at "
            "FROM chat_conversations c "
            "WHERE c.user_id=? AND c.course_id=? "
            "AND EXISTS ("
            "  SELECT 1 FROM chat_messages m "
            "  WHERE m.conversation_id = c.conversation_id AND m.role='user'"
            ") "
            "ORDER BY c.updated_at DESC LIMIT ?",
            (user_id, course_id, limit),
        )

    def set_conversation_title(self, conversation_id: str, title: str) -> None:
        self._conn().execute(
            "UPDATE chat_conversations SET title=?, updated_at=? WHERE conversation_id=?",
            (title, _now_iso(), conversation_id),
        )
        self._commit()

    # ---- course sources（user + course 双 scoped）------------------------
    def upsert_course_source(self, source: Dict[str, Any]) -> None:
        self._insert_or_update("course_sources", source, ["user_id", "course_id", "source_url"])

    def claim_course_source(self, source: Dict[str, Any]) -> Optional[dict]:
        """Atomically claim URL; an existing row keeps its stable source_id."""
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO course_sources (source_id,user_id,course_id,source_type,source_url,title,status,import_token,chunk_count,error_message,created_at,updated_at) "
                "VALUES (:source_id,:user_id,:course_id,:source_type,:source_url,:title,'importing',:import_token,:chunk_count,'',:created_at,:updated_at) "
                "ON CONFLICT(user_id,course_id,source_url) DO UPDATE SET "
                "source_type=excluded.source_type, title=excluded.title, status='importing', "
                "import_token=excluded.import_token, error_message='', updated_at=excluded.updated_at",
                source,
            )
            self._commit()
        except sqlite3.IntegrityError:
            self._conn().rollback()
            return None
        return self.get_course_source_by_url(source["user_id"], source["course_id"], source["source_url"])

    def touch_course_source_if_token(self, user_id: str, course_id: str,
                                     source_id: str, import_token: str) -> bool:
        cur = self._conn().execute(
            "UPDATE course_sources SET updated_at=updated_at WHERE user_id=? AND course_id=? AND source_id=? AND import_token=?",
            (user_id, course_id, source_id, import_token),
        )
        self._commit()
        return cur.rowcount == 1

    def finalize_course_source_if_token(self, source: Dict[str, Any]) -> bool:
        cur = self._conn().execute(
            "UPDATE course_sources SET status=?, import_token=?, chunk_count=?, error_message=?, updated_at=? "
            "WHERE user_id=? AND course_id=? AND source_id=? AND import_token=?",
            (source["status"], source["import_token"], source["chunk_count"], source.get("error_message", ""),
             source["updated_at"], source["user_id"], source["course_id"], source["source_id"], source["import_token"]),
        )
        self._commit()
        return cur.rowcount == 1

    def get_course_source(self, user_id: str, course_id: str, source_id: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM course_sources WHERE user_id=? AND course_id=? AND source_id=?",
            (user_id, course_id, source_id),
        )

    def get_course_source_by_url(self, user_id: str, course_id: str, url: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM course_sources WHERE user_id=? AND course_id=? AND source_url=?",
            (user_id, course_id, url),
        )

    def list_course_sources(self, user_id: str, course_id: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM course_sources WHERE user_id=? AND course_id=? "
            "ORDER BY updated_at DESC",
            (user_id, course_id),
        )

    def delete_course_source(self, user_id: str, course_id: str, source_id: str) -> None:
        self._conn().execute(
            "DELETE FROM course_sources WHERE user_id=? AND course_id=? AND source_id=?",
            (user_id, course_id, source_id),
        )
        self._commit()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
