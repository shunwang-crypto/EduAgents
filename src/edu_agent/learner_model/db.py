"""SQLite 连接管理 + Dynamic Learner Model Baseline Schema（SCHEMA_VERSION=1）。

正式 Baseline：
- 用户课程：user_courses（user-scoped；共享 Built-in Domain 为纯代码模板）
- 画像：learners / learner_profile_facts / learning_goals / learner_course_states /
  learner_kc_states / learner_preferences / learner_semantic_memories /
  learning_events / profile_change_log
- 产品：chat_conversations / chat_messages / study_plans / plan_steps
- 删除：domain_courses / domain_kcs / domain_kc_relations（个性化 Plan Nodes 只存
  plan_steps）；learner_abilities / learner_misconceptions / learner_evidences /
  adaptive_decisions / learner_state_snapshots；global_state_version / state_version
- 不做旧库迁移：旧开发阶段数据直接弃用，首次启动建干净表。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

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

-- 用户课程（User Course = 用户拥有/创建/加入；与共享 Domain Course 严格分离）
CREATE TABLE IF NOT EXISTS user_courses (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    topic TEXT DEFAULT '',
    normalized_topic TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id),
    UNIQUE (user_id, normalized_topic)
);
CREATE INDEX IF NOT EXISTS idx_user_courses_user ON user_courses(user_id);

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

CREATE TABLE IF NOT EXISTS learner_course_states (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    current_goal_id TEXT DEFAULT '',
    progress REAL DEFAULT 0.0,
    current_stage TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS learner_kc_states (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    kc_id TEXT NOT NULL,
    kc_name TEXT DEFAULT '',
    mastery REAL,
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

-- 聊天（ChatGPT 风格正式保存）
CREATE TABLE IF NOT EXISTS chat_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT DEFAULT '',
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user_course ON chat_conversations(user_id, course_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES chat_conversations(conversation_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON chat_messages(conversation_id, created_at);

-- 学习计划
CREATE TABLE IF NOT EXISTS study_plans (
    plan_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    goal_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    plan_markdown TEXT NOT NULL,
    progress REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_course ON study_plans(user_id, course_id);

CREATE TABLE IF NOT EXISTS plan_steps (
    step_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    stage_id TEXT NOT NULL DEFAULT 'stage-1',
    stage_title TEXT NOT NULL DEFAULT '',
    stage_order INTEGER NOT NULL DEFAULT 1,
    kc_id TEXT DEFAULT '',
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    learning_objective TEXT DEFAULT '',
    prerequisites_json TEXT DEFAULT '[]',
    difficulty TEXT DEFAULT '',
    minutes INTEGER DEFAULT 30,
    status TEXT DEFAULT 'not_started',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (plan_id, seq),
    FOREIGN KEY (plan_id) REFERENCES study_plans(plan_id) ON DELETE CASCADE
);
"""


def connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：LearnerModelService 进程级共享连接（单例避免 WAL 多连接锁），
    # 而 FastAPI 同步路由在线程池执行，连接会被不同线程复用。
    # SQLite threadsafety=SERIALIZED + WAL + busy_timeout + 短事务（transaction()）下跨线程安全。
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建 Baseline 表（幂等）。"""
    conn.executescript(_DDL)
    conn.commit()


def get_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    conn = connect(db_path)
    init_db(conn)
    return conn
