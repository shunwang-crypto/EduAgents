# 存储架构（Storage Architecture）

## 数据分层（本地原型）

| 数据 | 位置 | 特性 |
|---|---|---|
| **动态学习者画像** | `data/learner_model.db`（SQLite） | 唯一 Source of Truth；支持增删改/强化/弱化/失效/解决 |
| 学习事件（历史） | SQLite `learning_events` 表 | append-only，与当前状态分离 |
| 画像变更记录 | SQLite `profile_change_log` 表 | 每次画像改动可回放 |
| 画像快照 | SQLite `learner_state_snapshots` 表 | 每累计 N 个有意义事件生成 |
| 短期会话状态 | `data/cache_adaptive-session-*.json` | TTL 1h，不落长期画像 |
| 学习计划 + 学生输入 | `data/study_plan.json` | 业务数据 |
| 知识库问答会话 | `data/kb_sessions.json` | 业务数据 |
| 导入的知识库 | `data/knowledge_base.json` | RAG 素材 |

## 生产迁移契约（不改变画像逻辑）

| 层 | 原型 | 生产 | 说明 |
|---|---|---|---|
| Learner Model Repository | `sqlite_repository.py` | PostgreSQL（替换 `repository.py` 实现） | 表结构一一对应 |
| 画像缓存/Session | JSON | Redis（key `adaptive-session:{user_id}:{course_id}:{session_id}`） | TTL 语义一致 |
| Semantic Memory | SQLite 表 | Qdrant 向量库 | `learner_semantic_memories` 可迁 |

## 存储原则

1. **不复制第二套画像**：唯一真值在 SQLite Learner Model；`study_plan.json` 等只存业务数据。
2. **不把精确状态放非结构化位置**：mastery 等精确数值只存在于结构化表。
3. **事件与状态分离**：`learning_events` 只增；画像表可改可删。
4. **敏感删除最小化**：用户明确删除的 Fact/Memory，change log 不保存内容副本。
