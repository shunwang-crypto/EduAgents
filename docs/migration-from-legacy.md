# 迁移记录（migration-from-legacy）

## 本次迁移（2026-08-10）：Partner 画像 → 本地 SQLite Dynamic Learner Model

### 背景

此前两轮重构的方向是「合作伙伴 Learner Model 作为 Source of Truth，EduAgents 只读画像并回传事件」。
该前提取消（合作伙伴画像系统尚未完成，不能依赖任何上游服务）。

### 删除

| 内容 | 原因 |
|---|---|
| `src/edu_agent/integrations/`（provider/adapter/mock/remote/cache/event_emitter） | Partner 架构整体废弃 |
| `LEARNER_STATE_*`、`LEARNING_EVENT_DELIVERY_*` 环境变量 | 无外部服务 |
| `docs/learner-state-contract.md` | 已被 `docs/learner-model-schema.md` 取代 |
| `docs/contracts/learner-state-v1/` | 移到 `docs/archive/learner-state-v1-contract/`（NOT RUNTIME） |
| `data/learning_event_outbox.json`、`data/cache_learner-state-*.json` | Partner 时代残留数据 |
| 旧测试（`test_learner_state_adapter/provider/schemas`、`test_learning_events`、`test_architecture_contracts`） | 对象已删除 |

### 新增

| 内容 | 说明 |
|---|---|
| `learner_model/db.py` | SQLite DDL（12 表） |
| `learner_model/sqlite_repository.py` + `repository.py` | 仓库实现 + 抽象接口（未来可换 PostgreSQL） |
| `learner_model/service.py` | 业务门面：事件闭环 / 画像操作 |
| `learner_model/change_log.py` / `snapshot.py` | 变更记录 / 快照 |
| `learner_model/evidence/` | 事件 → 结构化证据 |
| `learner_model/updaters/` | knowledge/ability/preference/misconception/profile_fact/semantic_memory/goal/behavior |
| `docs/learner-model-schema.md` | 本地画像 schema 文档 |
| 新测试（`test_learner_model.py` 等，37 用例） | 生命周期/闭环/契约 |

### 复用（未改动）

- `adaptive/`（context_selector/temporal_resolver/policy/prompt_builder/policies/）—— 纯算法，改数据源
- `domain/learning/`（KC Graph / KST-lite）
- `workflows/`（study_plan/topic_tutor/kb_qa/plan_chat）—— 通过 `learner_context` 字符串接入
- `core/llm.py`、`tools/`（知识库/状态存储）

### 早期迁移（2026-08 更早轮次，已生效）

- `workflows/quiz/`、`quiz_generation/`、`mistake_reflection/` 已物理删除
- `core/mastery.py`（±delta 本地变更）、`core/student_profile.py`（第二套画像）已删除
- `PracticePlan` / `practice_task` / `practice_directions` 等练习字段已删除
