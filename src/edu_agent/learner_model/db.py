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
-- category_id：课程分类（course_categories.category_id）；NULL = 未分类。
-- FK ON DELETE SET NULL 是数据库最终防线：删除分类 → 课程自动未分类，课程本身绝不删除。
-- Category 只是组织层：Course 的 Adaptive 数据（goal/state/KC/memory/plan/sources）一律 course scoped。
CREATE TABLE IF NOT EXISTS user_courses (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    topic TEXT DEFAULT '',
    normalized_topic TEXT DEFAULT '',
    category_id TEXT REFERENCES course_categories(category_id) ON DELETE SET NULL,
    duration_days INTEGER NOT NULL DEFAULT 14 CHECK(duration_days BETWEEN 1 AND 365),
    daily_minutes INTEGER NOT NULL DEFAULT 60 CHECK(daily_minutes BETWEEN 5 AND 600),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id),
    UNIQUE (user_id, normalized_topic)
);
CREATE INDEX IF NOT EXISTS idx_user_courses_user ON user_courses(user_id);

-- 课程分类（Course Category）：纯组织层（用户自己创建的课程分组）。
-- 唯一职责是把 Course 分组；不拥有 mastery / KC / goal / state / memory /
-- plan / progress / RAG / sources / conversation / evidence 中的任何一项。
-- V1 只有一层（无 parent_category_id / level / path / tree）。
CREATE TABLE IF NOT EXISTS course_categories (
    category_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_course_categories_user
    ON course_categories(user_id, updated_at);

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
    PRIMARY KEY (user_id, goal_id),
    CHECK (progress >= 0 AND progress <= 1)
);

CREATE TABLE IF NOT EXISTS learner_course_states (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    current_goal_id TEXT DEFAULT '',
    progress REAL DEFAULT 0.0,
    current_stage TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id),
    CHECK (progress >= 0 AND progress <= 1)
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
    PRIMARY KEY (user_id, course_id, kc_id),
    CHECK (mastery IS NULL OR (mastery >= 0 AND mastery <= 1)),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
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
    plan_brief_json TEXT DEFAULT '{}',
    progress REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, course_id),  -- 每 User Course 只有一个 current plan
    CHECK (progress >= 0 AND progress <= 1)
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
    lesson_markdown TEXT DEFAULT '',
    lesson_generated_at TEXT DEFAULT '',
    status TEXT DEFAULT 'not_started',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (plan_id, seq),
    FOREIGN KEY (plan_id) REFERENCES study_plans(plan_id) ON DELETE CASCADE,
    CHECK (status IN ('not_started', 'in_progress', 'completed')),
    CHECK (stage_order BETWEEN 1 AND 3),
    CHECK (minutes > 0)
);

-- 结构化讲解（Structured Explanation；替换旧 lesson_markdown 长文）。
-- additive：不删除 lesson_markdown 列，新旧并存兼容旧数据。
CREATE TABLE IF NOT EXISTS step_explanations (
    explanation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    plan_id TEXT NOT NULL DEFAULT '',
    step_id TEXT NOT NULL,
    kc_id TEXT NOT NULL DEFAULT '',
    schema_version INTEGER NOT NULL DEFAULT 1,
    content_json TEXT NOT NULL DEFAULT '{}',
    context_hash TEXT NOT NULL DEFAULT '',
    generated_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    UNIQUE (step_id)
);
CREATE INDEX IF NOT EXISTS idx_exp_step ON step_explanations(step_id, course_id);

-- 课程资料（Course Sources：用户导入的 Web / GitHub 学习资料；user-scoped）
-- import_token：每次 import attempt 的 generation 身份（同 URL 多代请求并发时区分新旧，
--   旧请求 success/failure 不得覆盖新代）。
-- FK (user_id, course_id) → user_courses ON DELETE CASCADE：DB 最终防线——
--   删除 Course 时 course_sources metadata 级联清除，杜绝 orphan metadata。
CREATE TABLE IF NOT EXISTS course_sources (
    source_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'importing',
    import_token TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, course_id, source_url),
    CHECK (source_type IN ('web', 'github')),
    CHECK (status IN ('importing', 'ready', 'failed')),
    FOREIGN KEY (user_id, course_id)
        REFERENCES user_courses(user_id, course_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_course_sources_user_course
    ON course_sources(user_id, course_id, updated_at);

-- 动态 KCGraph 快照（Dynamic Knowledge Graph 的 canonical 来源）。
-- 每个 (user_id, course_id) 保存一份用户动态生成的知识结构：
-- 当用户的学习目标触发 Study Plan 生成时，KnowledgeMap 草稿经过 canonicalizer
-- 规范化后得到 canonical KC IDs，并持久化为本表。Learning Map / Tutor / Adaptive
-- Planner / Learner Model 都引用同一批 canonical IDs。
-- nodes/edges 以 JSON 存储（紧凑、可重建成 domain KCGraph）。
-- graph_source: generated / builtin / legacy
-- 这是 additive schema（SCHEMA_VERSION 不变），旧库首次启动自动建表，不破坏已有数据。
CREATE TABLE IF NOT EXISTS course_kc_graph (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    graph_source TEXT NOT NULL DEFAULT 'generated',
    graph_version INTEGER NOT NULL DEFAULT 1,
    generated_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    nodes_json TEXT NOT NULL DEFAULT '[]',
    edges_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (user_id, course_id)
);
CREATE INDEX IF NOT EXISTS idx_course_kc_graph_user
    ON course_kc_graph(user_id, updated_at);
"""


def connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # 每线程一条连接（SQLiteLearnerRepository 用 threading.local），
    # 连接只在创建它的线程内使用 → 保持 SQLite 默认 check_same_thread=True（更安全）。
    # WAL + busy_timeout + 短事务（transaction()）保证多线程并发安全。
    conn = sqlite3.connect(str(path), timeout=10)
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
