# 数据库迁移（SQLite Migrations）

## 机制

- 版本记录：`PRAGMA user_version`。
- `src/edu_agent/learner_model/migrations.py` 维护 `CURRENT_SCHEMA_VERSION` 与 `MIGRATIONS` 注册表。
- `migrate(conn)`：读取当前版本 → 依序执行未应用的 migration（每个单事务）→ 更新 user_version。
- 幂等：已执行版本跳过；失败：当前事务 rollback（历史版本不受影响）。

## 版本历史

### V1（初始）

12 张表：`learners` / `learner_profile_facts` / `learning_goals` / `learner_course_states` /
`learner_kc_states` / `learner_abilities` / `learner_preferences` / `learner_misconceptions` /
`learner_semantic_memories` / `learning_events` / `profile_change_log` / `learner_state_snapshots`

### V2（unknown 语义 + 双版本 + 新表）

1. `learners` 增加 `global_state_version`（默认 1）。
2. 数据迁移（区分 UNKNOWN 与 KNOWN ZERO）：
   - `learner_kc_states`：`status='unknown' AND confidence IS NULL AND mastery=0` → `mastery=NULL`；
     已知低掌握度（有置信度）的 `mastery=0` 保留。
   - `learner_abilities`：`confidence IS NULL AND score=0` → `score=NULL`。
3. `learning_goals` 重建为联合主键 `(user_id, goal_id)`（多用户隔离）。
4. 新表：
   - `learner_evidences`（事件→证据，唯一键 `(event_id, entity_type, entity_key, classifier_version)`）
   - `adaptive_decisions`（自适应决策日志）
   - `domain_courses` / `domain_kcs` / `domain_kc_relations`（自定义课程 Domain Model 持久化）

## 测试

- `test_migration_fresh_db`：fresh DB 迁移到最新版本，新表存在。
- `test_migration_v1_to_v2_unknown_to_null`：V1 库（unknown+0 mastery）迁移后 mastery=NULL；
  known-zero（0+confidence=0.9）保留 0；goals 主键变为联合。
