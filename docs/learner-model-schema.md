# 本地 Learner Model Schema（SQLite）

> 本文档定义本地动态学习者模型的表结构与字段语义。
> `data/learner_model.db` 是唯一 Source of Truth。
> （旧 `docs/learner-state-contract.md` 描述的 Partner 对接契约已废弃，见 `docs/archive/`。）

## 设计原则

- Mastery 与 Confidence 严格分离：
  - `mastery=.20 + confidence=.95` → 基本确定学生不会（KNOWN LOW）；
  - `mastery=.20 + confidence=.15` → 数据不足，不能武断（LOW BUT UNCERTAIN）；
  - `mastery=NULL` → UNKNOWN（从未有证据），**不是 0**。
- 未知值用 NULL，禁止编造（`confidence=NULL` = 无证据）。
- 所有课程状态以 `(user_id, course_id)` 隔离；全局状态带 `global_state_version`。
- 画像可增删改；Events append-only。
- Schema 升级走 `docs/database-migrations.md` 的迁移机制（PRAGMA user_version）。

## 表结构

### 1. `learners` — 用户稳定身份
`user_id`(PK) / `display_name` / `education_level` / `language` / `background` /
`global_state_version`（全局画像版本）/ `created_at` / `updated_at`

### 2. `learner_profile_facts` — 可变化背景事实
`fact_id`(PK) / `user_id` / `category` / `fact_key` / `fact_value_json` / `confidence` /
`source`(USER_EXPLICIT|...) / `status`(candidate|active|inactive) / `first_observed_at` /
`last_confirmed_at` / `updated_at` / `expires_at`
- **同 `user_id + fact_key` 唯一**：冲突时 UPDATE，不追加第二条。
- 用户显式修正时 confidence **重设**（不保留旧 max 误导）。

### 3. `learning_goals` — 学习目标（可多个，多用户隔离）
`(user_id, goal_id)`(联合 PK) / `course_id` / `name` / `target` / `priority` /
`status`(active|paused|completed|cancelled) / `progress` / `target_kcs_json` / `deadline` / `created_at` / `updated_at`

### 4. `learner_course_states` — 课程级状态
`(user_id, course_id)`(PK) / `current_goal_id` / `progress` / `current_stage` / `state_version`（课程画像版本）/ `updated_at`
- **禁止 `course_id=''` 的课程状态**（全局事件只动 global version）。

### 5. `learner_kc_states` — 知识点掌握度（最重要）
`(user_id, course_id, kc_id)`(PK) / `kc_name` / `mastery`(可 NULL=UNKNOWN) / `confidence`(可 NULL) /
`status`(weak|learning|mastered|unknown) / `trend` / `evidence_count` /
`first_evidence_at` / `last_evidence_at` / `is_estimated` / `created_at` / `updated_at`
- **`mastery=NULL` 与 `mastery=0+高置信` 严格区分**（V2 迁移已把 unknown 的 0 转 NULL）。

### 6. `learner_abilities` — 六维能力
`(user_id, course_id, ability_type)`(PK) / `score` / `confidence` / `trend` / `evidence_count` / `first_evidence_at` / `last_evidence_at` / `updated_at`
- 慢更新（小学习率 EMA），弱证据只计数。

### 7. `learner_preferences` — 偏好（完整生命周期）
`(user_id, course_id, preference_key)`(PK) / `score` / `confidence` / `evidence_count` /
`status`(candidate|active|weakening|inactive) / `first_observed_at` / `last_observed_at` / `created_at` / `updated_at`
- `course_id=''` = 跨课程长期偏好；非空 = 课程特定偏好。
- 生命周期：candidate → active（confidence≥0.5）→ weakening（连续负向+conf<0.35）→
  inactive（conf<0.15）→ reactivate（正向 → candidate/active）。USER_EXPLICIT 最高优先级。
- 键：`worked_example` / `step_by_step` / `diagram` / `code_example` / `analogy` / `concise_first` / `concept_first`

### 8. `learner_misconceptions` — 误解（多实例 + 完整生命周期）
`misconception_id`(PK) / `user_id` / `course_id` / `kc_id` / `misconception_key` / `type` / `description` /
`severity` / `confidence` / `occurrence_count` / `status`(candidate|active|resolving|resolved) /
`first_seen_at` / `last_seen_at` / `resolved_at` / `created_at` / `updated_at`
- **同一 KC 可同时存在多个误解**：`(user_id, course_id, kc_id, misconception_key)` 逻辑唯一
  （如 `static_vs_dynamic_type` 与 `overload_vs_override` 并存）。

### 9. `learner_semantic_memories` — 长期语义记忆（课程隔离）
`memory_id`(PK) / `user_id` / `course_id`(可 ''=global) / `category` / `content` / `confidence` / `importance` /
`source` / `status`(candidate|active|inactive) / `first_seen_at` / `last_reinforced_at` / `updated_at` / `expires_at`
- 当前课程上下文 = 全局记忆 + 本课程记忆（**不含其他课程**）。

### 10. `learning_events` — 历史事件（append-only + 幂等）
`event_id`(PK) / `schema_version` / `event_type` / `user_id` / `course_id` / `goal_id` / `kc_id` /
`session_id` / `timestamp` / `source` / `evidence_strength`(weak|medium|strong) / `payload_json` / `created_at`
- 同 event_id 重复 apply → 幂等跳过（不重复应用证据）。

### 11. `learner_evidences` — 结构化证据（provenance）
`evidence_id`(PK) / `event_id` / `event_type` / `user_id` / `course_id` / `kc_id` /
`entity_type` / `entity_key` / `direction` / `weight` / `source` / `classifier_version` /
`confidence` / `meaningful_for_profile` / `payload_json` / `created_at`
- 唯一键 `(event_id, entity_type, entity_key, classifier_version)`：重放不重复强化。

### 12. `profile_change_log` — 画像变更记录（真实 before/after）
`change_id`(PK) / `user_id` / `course_id` / `entity_type` / `entity_id` / `operation`
(CREATE|UPDATE|REINFORCE|WEAKEN|DEACTIVATE|REACTIVATE|RESOLVE|DELETE|MERGE) /
`before_json` / `after_json` / `reason` / `evidence_ids_json` / `created_at`
- 普通变更保存字段级 before/after（如 `score 0.61 → 0.68`）；
- 用户明确 DELETE：不保存被删内容全文，只留 entity_id + operation + 时间。

### 13. `learner_state_snapshots` — 画像快照
`snapshot_id`(PK) / `user_id` / `course_id` / `state_version` / `snapshot_json` / `created_at`
- 按**状态版本**触发（`course_state_version % interval == 0`），不按事件数。

### 14. `adaptive_decisions` — 自适应决策日志
`decision_id`(PK) / `user_id` / `course_id` / `goal_id` / `session_id` / `task_type` / `target_kc` /
`global_state_version` / `course_state_version` / `selected_context_json` / `temporal_state_json` /
`decision_json` / `reason_codes_json` / `policy_version` / `created_at`
- 只在真正执行教学动作时写入（生成计划/讲解/回答），不在 render 时写。

### 15-17. `domain_courses` / `domain_kcs` / `domain_kc_relations` — 自定义课程 Domain Model
- 学习计划生成后由 KnowledgeMap 构建并持久化；应用重启后恢复（多课程模型见 `docs/multi-course-model.md`）。

## 数据来源

- 首次用户：`ensure_learner` 建 minimal learner（无编造 mastery，confidence 低）。
- 学习行为：`LearningEvent → EvidenceExtractor（规则+语义分类） → Updater` 定向更新。
- 用户显式输入：`USER_EXPLICIT_*` 事件（最高优先级）。
- 强证据（`CHECK_UNDERSTANDING_RESPONSE`）才允许小幅初始化/更新 mastery；弱证据只更新曝光/置信度。
