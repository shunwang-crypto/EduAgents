"""正式 SQLite Migration 系统。

- 版本记录：PRAGMA user_version。
- CURRENT_SCHEMA_VERSION：当前期望版本。
- 每个 migration 是 (version, name, fn)：fn 接收 conn，执行 DDL/DML，单事务。
- migrate(conn)：读取当前版本 → 依序执行 → 每步事务 → 更新 user_version。
- 幂等：已执行版本跳过；失败：当前事务 rollback（历史版本不受影响）。
"""

from __future__ import annotations

import sqlite3
from typing import Callable, List, Tuple

CURRENT_SCHEMA_VERSION = 2

MigrationFn = Callable[[sqlite3.Connection], None]

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def _migration_001_initial(conn: sqlite3.Connection) -> None:
    """V1 初始表（首次建库 / 老库无版本标记时补齐）。"""
    from edu_agent.learner_model.db import init_v1

    init_v1(conn)


def _migration_002_nullable_unknown_and_versions(conn: sqlite3.Connection) -> None:
    """V1 → V2：

    1. learners 增加 global_state_version。
    2. 数据迁移：unknown 且无证据的 mastery=0 / score=0 → NULL（区分 unknown 与 known zero）。
    3. learning_goals 重建为 (user_id, goal_id) 联合身份（多用户隔离）。
    4. 新表：learner_evidences / adaptive_decisions / domain_courses / domain_kcs / domain_kc_relations。
    """
    # 1) global_state_version
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(learners)").fetchall()}
    if "global_state_version" not in cols:
        conn.execute(
            "ALTER TABLE learners ADD COLUMN global_state_version INTEGER DEFAULT 1"
        )

    # 2) unknown mastery → NULL（仅当 status='unknown' 且 confidence IS NULL 且 mastery=0）
    conn.execute(
        "UPDATE learner_kc_states SET mastery=NULL "
        "WHERE status='unknown' AND confidence IS NULL AND mastery=0"
    )
    conn.execute(
        "UPDATE learner_abilities SET score=NULL "
        "WHERE confidence IS NULL AND score=0"
    )

    # 3) learning_goals 重建为联合主键 (user_id, goal_id)
    _rebuild_goals(conn)

    # 4) 新表
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS learner_evidences (
            evidence_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            user_id TEXT NOT NULL,
            course_id TEXT DEFAULT '',
            kc_id TEXT DEFAULT '',
            entity_type TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            direction TEXT NOT NULL,
            weight REAL DEFAULT 0.0,
            source TEXT DEFAULT 'SYSTEM_OBSERVATION',
            classifier_version TEXT DEFAULT 'rule-v1',
            confidence REAL,
            meaningful_for_profile INTEGER DEFAULT 0,
            payload_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (event_id, entity_type, entity_key, classifier_version)
        );
        CREATE INDEX IF NOT EXISTS idx_evidences_user_course
            ON learner_evidences(user_id, course_id, created_at);

        CREATE TABLE IF NOT EXISTS adaptive_decisions (
            decision_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            course_id TEXT DEFAULT '',
            goal_id TEXT DEFAULT '',
            session_id TEXT DEFAULT '',
            task_type TEXT NOT NULL,
            target_kc TEXT DEFAULT '',
            global_state_version INTEGER,
            course_state_version INTEGER,
            selected_context_json TEXT,
            temporal_state_json TEXT,
            decision_json TEXT NOT NULL,
            reason_codes_json TEXT DEFAULT '[]',
            policy_version TEXT DEFAULT 'rule-v1',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_user
            ON adaptive_decisions(user_id, created_at);

        CREATE TABLE IF NOT EXISTS domain_courses (
            course_id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            topic TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS domain_kcs (
            course_id TEXT NOT NULL,
            kc_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            category TEXT DEFAULT 'core',
            description TEXT DEFAULT '',
            difficulty TEXT DEFAULT 'medium',
            PRIMARY KEY (course_id, kc_id)
        );

        CREATE TABLE IF NOT EXISTS domain_kc_relations (
            course_id TEXT NOT NULL,
            from_kc TEXT NOT NULL,
            to_kc TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            PRIMARY KEY (course_id, from_kc, to_kc, relation)
        );
        """
    )


def _rebuild_goals(conn: sqlite3.Connection) -> None:
    """learning_goals → (user_id, goal_id) 联合主键（标准 12 步重建）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(learning_goals)").fetchall()}
    if cols and "user_id" in cols:
        pk = conn.execute(
            "SELECT l.name FROM pragma_table_info('learning_goals') l WHERE l.pk>0"
        ).fetchall()
        pk_names = [r["name"] for r in pk]
        if pk_names == ["user_id", "goal_id"]:
            return  # 已是新结构
    conn.executescript(
        """
        CREATE TABLE learning_goals_v2 (
            goal_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            course_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            target TEXT DEFAULT '',
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            progress REAL DEFAULT 0.0,
            target_kcs_json TEXT DEFAULT '[]',
            deadline TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, goal_id)
        );
        INSERT INTO learning_goals_v2 (goal_id, user_id, course_id, name, target, priority,
            status, progress, target_kcs_json, deadline, created_at, updated_at)
            SELECT goal_id, user_id, course_id, name, target, priority, status, progress,
                   target_kcs_json, deadline, created_at, updated_at FROM learning_goals;
        DROP TABLE learning_goals;
        ALTER TABLE learning_goals_v2 RENAME TO learning_goals;
        """
    )


# Migration Registry：(version, name, fn)
MIGRATIONS: List[Tuple[int, str, MigrationFn]] = [
    (1, "initial", _migration_001_initial),
    (2, "nullable_unknown_and_versions", _migration_002_nullable_unknown_and_versions),
]


def migrate(conn: sqlite3.Connection) -> int:
    """把数据库迁移到最新版本，返回最终版本号。"""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, _name, fn in MIGRATIONS:
        if version <= current:
            continue
        try:
            fn(conn)
            conn.execute(f"PRAGMA user_version={version}")
            conn.commit()
            current = version
        except Exception:
            conn.rollback()
            raise
    return current


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]
