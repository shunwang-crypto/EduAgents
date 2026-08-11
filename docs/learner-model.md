# Dynamic Learner Model

本地 SQLite Learner Model 是**唯一**的学习者画像真值。前端 / API / 应用服务均不维护第二套画像。

## 原则

- **UNKNOWN ≠ 0**：`mastery = NULL` 表示"没有证据，不知道"；`mastery = 0 + confidence 高` 才表示"有可靠证据表明不会"。两者严格不同，任何地方都不允许把 None 悄悄转成 0。
- **保守更新**：普通浏览、讲解完成、"懂了"等弱证据**不得**自动抬高 mastery。只有用户显式声明或可靠证据才改变数值。
- **用户显式声明 > 推断**：`USER_EXPLICIT_*` 事件优先。
- **多课程隔离**：所有课程级状态以 `(user_id, course_id)` 隔离；全局状态（profile fact / 全局 preference / global memory）可跨课程共享，课程状态绝不跨课程泄漏。
- **真正删除**：用户明确删除 Fact / Memory 时物理删除；change log 只留最小审计（entity id + operation + 时间），不保存被删内容副本。

## Schema（SCHEMA_VERSION=1，干净基线，无历史 migration 兼容）

| 表 | 用途 |
|---|---|
| `learners` | 用户身份 |
| `learner_profile_facts` | 背景事实（同 `user_id+fact_key` 唯一，可 UPDATE；保留 False/0/"" 值） |
| `learning_goals` | 学习目标（`(user_id, goal_id)` 联合主键，多用户隔离；一课程一个 active goal） |
| `learner_course_states` | 课程状态（progress / current_goal_id） |
| `learner_kc_states` | 知识点掌握度（mastery 可 NULL；confidence 分离） |
| `learner_preferences` | 偏好（`(user_id, course_id, key)`；course_id='' = 全局；完整生命周期） |
| `learner_semantic_memories` | 长期记忆（course_id='' = 全局，否则课程隔离） |
| `learning_events` | 事件（append-only，event_id 幂等） |
| `profile_change_log` | 画像变更记录（before/after 数值） |
| `chat_conversations` / `chat_messages` | 对话历史（按 user + course 隔离） |
| `study_plans` / `plan_steps` | 学习计划与步骤（progress 正式来源） |
| `user_courses` | 用户课程（user-scoped；共享 Built-in Domain 为纯代码模板） |

## 事件 → 状态更新（统一事务）

所有画像变更走 `LearnerModelService`：

```
BEGIN
├─ insert event（幂等：event_id 已存在则整体 no-op）
├─ 提取 LightEvidence（确定性规则，无 LLM 重写画像）
├─ 定向 Updater（knowledge / preference / profile_fact / goal / semantic_memory）
├─ before / after → change log
└─ COMMIT（任何异常 ROLLBACK，无半写状态）
```

- Repository 的 `transaction()` 是唯一 commit 方；Updater 不 commit。
- `ingest_event` 是唯一入口（auto_update 语义在 Service 内部收敛）。

## 事件类型（收缩后的全集）

`COURSE_CREATED / COURSE_UPDATED / COURSE_DELETED / GOAL_CREATED / GOAL_UPDATED /
PLAN_CREATED / PLAN_STEP_STARTED / PLAN_STEP_COMPLETED / CHAT_MESSAGE_SENT /
CHAT_RESPONSE_DELIVERED / USER_EXPLICIT_PROFILE_FACT / USER_EXPLICIT_PREFERENCE /
PROFILE_FACT_DELETED / MEMORY_CREATED / MEMORY_DELETED / FEEDBACK_GIVEN`

## 画像生命周期

仅对真实保留的实体实现：`CREATE / UPDATE / REINFORCE / WEAKEN / DEACTIVATE / DELETE`。
- Preference：`candidate → active → weakening → inactive → reactivate`（USER_EXPLICIT 最高优先级）。
- Profile Fact：同 key 冲突 UPDATE；用户修正时 confidence 重设（不是永远取 max）。
- Memory：`add_memory`（同内容去重 REINFORCE）/ `delete_memory`（真正删除）。

## 多课程

- `user_courses`（user_id, course_id, display_name, topic, normalized_topic）持久化用户课程；
  `course_resolver.py` 将 topic 稳定映射到 `CUSTOM-{slug}-{hash8}`，但 ownership 由 user_courses membership 决定。
- Java 课程的状态 / 计划 / 记忆不会进入 Python 课程的上下文；不同用户的同名课程完全隔离。
- 删除用户课程 = 级联删除该用户在该课程的全部数据（user_courses / states / goals / plans /
  steps / conversations / messages / kc_states / preferences / memories），共享模板不受影响。
