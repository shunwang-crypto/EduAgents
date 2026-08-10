# 本地 Learner Model Schema（SQLite）

> 本文档定义本地动态学习者模型的表结构与字段语义。
> `data/learner_model.db` 是唯一 Source of Truth。
> （旧 `docs/learner-state-contract.md` 描述的 Partner 对接契约已废弃，见 `docs/archive/`。）

## 设计原则

- Mastery 与 Confidence 严格分离：
  - `mastery=.20 + confidence=.95` → 基本确定学生不会；
  - `mastery=.20 + confidence=.15` → 数据不足，不能武断。
- 未知值用 NULL，禁止编造（`confidence=NULL` = 无证据）。
- 所有课程状态以 `(user_id, course_id)` 隔离。
- 画像可增删改；Events append-only。

## 表结构

### 1. `learners` — 用户稳定身份
`user_id`(PK) / `display_name` / `education_level` / `language` / `background` / `created_at` / `updated_at`

### 2. `learner_profile_facts` — 可变化背景事实
`fact_id`(PK) / `user_id` / `category` / `fact_key` / `fact_value_json` / `confidence` /
`source`(USER_EXPLICIT|...) / `status`(candidate|active|inactive) / `first_observed_at` /
`last_confirmed_at` / `updated_at` / `expires_at`
- **同 `user_id + fact_key` 唯一**：冲突时 UPDATE，不追加第二条。

### 3. `learning_goals` — 学习目标（可多个）
`goal_id`(PK) / `user_id` / `course_id` / `name` / `target` / `priority` / `status`(active|paused|completed|cancelled) / `progress` / `target_kcs_json` / `deadline` / `created_at` / `updated_at`

### 4. `learner_course_states` — 课程级状态
`(user_id, course_id)`(PK) / `current_goal_id` / `progress` / `current_stage` / `state_version` / `updated_at`

### 5. `learner_kc_states` — 知识点掌握度（最重要）
`(user_id, course_id, kc_id)`(PK) / `kc_name` / `mastery` / `confidence`(可 NULL) /
`status`(weak|learning|mastered|unknown) / `trend` / `evidence_count` /
`first_evidence_at` / `last_evidence_at` / `is_estimated` / `created_at` / `updated_at`

### 6. `learner_abilities` — 六维能力
`(user_id, course_id, ability_type)`(PK) / `score` / `confidence` / `trend` / `evidence_count` / `first_evidence_at` / `last_evidence_at` / `updated_at`
- 慢更新（小学习率 EMA），弱证据只计数。

### 7. `learner_preferences` — 偏好（可升可降）
`(user_id, course_id, preference_key)`(PK) / `score` / `confidence` / `evidence_count` /
`status`(candidate|active|weakening|inactive) / `first_observed_at` / `last_observed_at` / `created_at` / `updated_at`
- `course_id=''` = 跨课程长期偏好；非空 = 课程特定偏好。
- 键：`worked_example` / `step_by_step` / `diagram` / `code_example` / `analogy` / `concise_first` / `concept_first`

### 8. `learner_misconceptions` — 误解（完整生命周期）
`misconception_id`(PK) / `user_id` / `course_id` / `kc_id` / `type` / `description` /
`severity` / `confidence` / `occurrence_count` / `status`(candidate|active|resolving|resolved) /
`first_seen_at` / `last_seen_at` / `resolved_at` / `created_at` / `updated_at`

### 9. `learner_semantic_memories` — 长期语义记忆
`memory_id`(PK) / `user_id` / `course_id` / `category` / `content` / `confidence` / `importance` /
`source` / `status`(candidate|active|inactive) / `first_seen_at` / `last_reinforced_at` / `updated_at` / `expires_at`

### 10. `learning_events` — 历史事件（append-only）
`event_id`(PK) / `schema_version` / `event_type` / `user_id` / `course_id` / `goal_id` / `kc_id` /
`session_id` / `timestamp` / `source` / `evidence_strength`(weak|medium|strong) / `payload_json` / `created_at`

### 11. `profile_change_log` — 画像变更记录
`change_id`(PK) / `user_id` / `course_id` / `entity_type` / `entity_id` / `operation`
(CREATE|UPDATE|REINFORCE|WEAKEN|DEACTIVATE|REACTIVATE|RESOLVE|DELETE|MERGE) /
`before_json` / `after_json` / `reason` / `evidence_ids_json` / `created_at`
- 用户明确 DELETE：不保存被删内容全文，只留 entity_id + operation + 时间。

### 12. `learner_state_snapshots` — 画像快照
`snapshot_id`(PK) / `user_id` / `course_id` / `state_version` / `snapshot_json` / `created_at`
- 每累计 N 个有意义事件生成一次，用于调试/回放/实验。

## 数据来源

- 首次用户：`ensure_learner` 建 minimal learner（无编造 mastery，confidence 低）。
- 学习行为：`LearningEvent → EvidenceExtractor → Updater` 定向更新。
- 用户显式输入：`USER_EXPLICIT_*` 事件（最高优先级）。
