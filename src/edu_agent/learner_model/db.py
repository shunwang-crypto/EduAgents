"""SQLite 连接管理 + Learner Model 表结构（DDL）。

原则：
- ``data/learner_model.db`` 是本地 Dynamic Learner Model 的唯一 Source of Truth。
- 业务代码禁止直接执行 SQL，必须通过 Repository（sqlite_repository.py）。
- 所有课程状态以 (user_id, course_id) 隔离。
- Events 表 append-only；Learner State 表允许增删改。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

# 默认库路径（可用 LEARNER_MODEL_DB_PATH 覆盖）
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "learner_model.db"

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS learners (
    user_id TEXT PRIMARY KEY,
    display_name TEXT DEFAULT '',
    education_level TEXT DEFAULT '',
    language TEXT DEFAULT 'zh',
    background TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learner_profile_facts (
    fact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT DEFAULT 'background',
    fact_key TEXT NOT NULL,
    fact_value_json TEXT NOT NULL,
    confidence REAL DEFAULT 0.3,
    source TEXT DEFAULT 'USER_EXPLICIT',
    status TEXT DEFAULT 'active',
    first_observed_at TEXT,
    last_confirmed_at TEXT,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    UNIQUE (user_id, fact_key)
);

CREATE TABLE IF NOT EXISTS learning_goals (
    goal_id TEXT PRIMARY KEY,
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
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learner_course_states (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    current_goal_id TEXT DEFAULT '',
    progress REAL DEFAULT 0.0,
    current_stage TEXT DEFAULT '',
    state_version INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS learner_kc_states (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    kc_id TEXT NOT NULL,
    kc_name TEXT DEFAULT '',
    mastery REAL DEFAULT 0.0,
    confidence REAL,
    status TEXT DEFAULT 'unknown',
    trend TEXT,
    evidence_count INTEGER DEFAULT 0,
    first_evidence_at TEXT,
    last_evidence_at TEXT,
    is_estimated INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id, kc_id)
);

CREATE TABLE IF NOT EXISTS learner_abilities (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    ability_type TEXT NOT NULL,
    score REAL DEFAULT 0.0,
    confidence REAL,
    trend TEXT,
    evidence_count INTEGER DEFAULT 0,
    first_evidence_at TEXT,
    last_evidence_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id, ability_type)
);

CREATE TABLE IF NOT EXISTS learner_preferences (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL DEFAULT '',
    preference_key TEXT NOT NULL,
    score REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.1,
    evidence_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'candidate',
    first_observed_at TEXT,
    last_observed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id, preference_key)
);

CREATE TABLE IF NOT EXISTS learner_misconceptions (
    misconception_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    kc_id TEXT NOT NULL,
    type TEXT DEFAULT 'conceptual_confusion',
    description TEXT DEFAULT '',
    severity REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.3,
    occurrence_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'candidate',
    first_seen_at TEXT,
    last_seen_at TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learner_semantic_memories (
    memory_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT DEFAULT '',
    category TEXT DEFAULT 'experience',
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    importance REAL DEFAULT 0.5,
    source TEXT DEFAULT 'USER_EXPLICIT',
    status TEXT DEFAULT 'active',
    first_seen_at TEXT,
    last_reinforced_at TEXT,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS learning_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER DEFAULT 1,
    event_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    course_id TEXT DEFAULT '',
    goal_id TEXT DEFAULT '',
    kc_id TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    timestamp TEXT NOT NULL,
    source TEXT DEFAULT 'SYSTEM_OBSERVATION',
    evidence_strength TEXT DEFAULT 'weak',
    payload_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user_course ON learning_events(user_id, course_id, timestamp);

CREATE TABLE IF NOT EXISTS profile_change_log (
    change_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT DEFAULT '',
    entity_type TEXT NOT NULL,
    entity_id TEXT DEFAULT '',
    operation TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT DEFAULT '',
    evidence_ids_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changelog_user ON profile_change_log(user_id, created_at);

CREATE TABLE IF NOT EXISTS learner_state_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    state_version INTEGER DEFAULT 1,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """打开（并初始化）Learner Model 数据库。"""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
    conn.executescript(_DDL)
    conn.commit()


def get_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """便捷入口：连接 + 初始化。"""
    conn = connect(db_path)
    init_db(conn)
    return conn
