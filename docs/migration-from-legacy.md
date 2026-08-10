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

## V1 正确性收口（2026-08-10 深夜，e2f9820 之后）

对本地 Dynamic Learner Model 做正确性收口（未推翻架构）：

- **UNKNOWN ≠ 0**：`mastery/score` 允许 NULL；首次观察 `mastery=None`；
  Adaptive Policy 区分 UNKNOWN（`UNKNOWN_KNOWLEDGE_STATE`）/ KNOWN LOW / LOW BUT UNCERTAIN。
- **正式 Migration**：`learner_model/migrations.py`（PRAGMA user_version + 注册表 + 事务）；
  V2 迁移把 unknown 的 `mastery=0/score=0` 转 NULL（known-zero 保留），`learning_goals` 重建为
  `(user_id, goal_id)` 联合主键，新增 `learner_evidences / adaptive_decisions / domain_*` 表。
- **事务一致性**：repository 事务化（updater 不 commit），`apply_event` 单事务，失败回滚。
- **Event 幂等**：`event_id` 重复 apply 跳过；evidence 唯一键防重复强化。
- **双版本**：`global_state_version` + `course state_version`；全局事件不创建 `course_id=''` 课程状态。
- **Evidence Pipeline**：`learner_evidences` 落库；`semantic_classifier` 高确定规则
  （普通"为什么"不误判误解）；`CHECK_UNDERSTANDING_RESPONSE` 提供真实 Ability/Mastery 证据来源。
- **实体修复**：misconception 多实例（`misconception_key`）；preference 完整 weakening 生命周期；
  profile_fact 保留 `False/0/""` + 显式修正重设 confidence；goal 多用户隔离；memory 课程隔离；
  behavior 30 天真实过滤 + session 时长不编造。
- **多课程**：`LearningContext` + `CourseResolver` + `domain_courses` 持久化（跨重启恢复）。
- **工作流闭环**：Study Plan 生成即创建 Goal/注册课程/PLAN_CREATED，level 可选；
  Topic Tutor 完整交互事件 + 自由文本理解检查；KB QA 增加 KC Mapper + FEEDBACK_GIVEN；
  `adaptive_decisions` 持久化（仅真实执行教学动作时）。
- 前端：unknown 显示、Global/Course 作用域标识、变化记录数值、首次画像初始化表单。

### 早期迁移（2026-08 更早轮次，已生效）

- `workflows/quiz/`、`quiz_generation/`、`mistake_reflection/` 已物理删除
- `core/mastery.py`（±delta 本地变更）、`core/student_profile.py`（第二套画像）已删除
- `PracticePlan` / `practice_task` / `practice_directions` 等练习字段已删除
- `integrations/`（Partner Provider/Adapter/Remote/Outbox）已删除，本地 SQLite 为唯一画像真值
