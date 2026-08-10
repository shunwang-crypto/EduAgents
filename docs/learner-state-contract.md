# LearnerState 契约（EduAgents ↔ 合作伙伴）

## 1. Source of Truth

合作伙伴 Learner Model 是以下数据的唯一真源：

- User Profile / Learning Goals / Preferences
- Knowledge Mastery / Mastery Confidence / Ability
- Misconception / Behavioral State / Evidence Aggregation
- Learner State History / Profile Update / Persistence

EduAgents **只读消费**，不维护第二套 profile/mastery。

## 2. 内部契约（`integrations/learner_state/schemas.py`）

### Global Learner State

| 字段 | 说明 |
| -- | -- |
| profile | user_id / display_name / education_level / language / background |
| goals[] | goal_id / course_id / goal_name / target / priority / status / progress / target_kcs |
| preferences | preferred_mode / learning_style_distribution / mode_effectiveness（score+confidence+sample_size）/ pace_factor / scaffold_preference |
| semantic_memory[] | 长期语义记忆（Qdrant/向量库），不存精确 mastery |

### Course Learner State

| 字段 | 说明 |
| -- | -- |
| schema_version / user_id / course_id / goal_id / progress | 基础标识 |
| knowledge[] | kc_id / name / mastery / **confidence** / status / trend / evidence_count / last_evidence_at / is_estimated |
| abilities{} | understanding / application / reasoning / expression / reflection / transfer（各带 score/confidence/trend/evidence_count） |
| misconceptions[] | misconception_id / kc_id / type / description / severity / confidence / occurrence_count / status / first_seen_at / last_seen_at |
| behavior | activity_count_30d / streak_days / average_session_minutes / recent_topics / frequent_revisited_topics |
| metadata | schema_version / state_version / updated_at |

**Mastery 与 Confidence 必须分离**：

```
mastery=.20 + confidence=.95  → 基本确定学生不会
mastery=.20 + confidence=.15  → 数据不足，不能武断
```

## 3. 建议的合作伙伴 API（EduAgents 内部契约）

```
GET  /api/v1/learners/{user_id}                        → profile + preferences + active_goals
GET  /api/v1/learners/{user_id}/courses/{course_id}/state → progress + knowledge + abilities + misconceptions + behavior + metadata
POST /api/v1/learners/{user_id}/events                 → EduAgents 回传 LearningEvent
```

若合作伙伴当前字段不同：**只用 `adapter.py` 适配，不污染 Adaptive Engine。**

## 4. 已对接的合作伙伴现状（killoppen/-）

合作伙伴 backend 已提供：

- `GET /api/students/{student_id}/learning-state`
- `GET /api/students/{student_id}/profile` / `portrait`
- `POST /api/upstream/assessment-result`（`event_id` 幂等）

`remote_provider.py` 默认命中这些路径；字段差异在 `adapter.py` 中宽容解析。

## 5. 版本与新鲜度

- `state_version` / `updated_at`：判断缓存是否过期
- AdaptiveDecision 记录 `learner_state_version`，便于调试与实验
- `freshness`：fresh / stale / mock / missing（决策上下文必须标注）

## 6. 缓存

```
Redis key: learner-state:{user_id}:{course_id}（短 TTL）
```

当前原型用 `data/cache_learner-state-*.json`，接口可替换。
