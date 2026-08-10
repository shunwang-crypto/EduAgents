# 自适应学习架构（Local Dynamic Learner Model 版）

> 本文档是当前代码的权威架构说明。旧「Partner Learner Model 作为 Source of Truth」
> 的设计已废弃，见 `docs/archive/learner-state-v1-contract/`（NOT RUNTIME）。

## 1. 定位

EduAgents = **具有本地动态学习者模型的自适应学习规划与个性化辅导系统**。

- **Dynamic Learner Model**：回答"这个学生现在是什么状态？"（本地 SQLite 维护）
- **Adaptive Learning Engine**：回答"面对这个状态，现在应该怎么学、怎么教？"（规则策略）
- **LLM**：只执行教学策略，生成内容，不承担完整个性化决策。

## 2. 总架构

```
Observe（用户行为）
   │
   ▼
LearningEvent（append-only 历史）
   │
   ▼
EvidenceExtractor（事件 → StructuredEvidence）
   │
   ▼
Updaters（8 个定向更新器）
   │
   ▼
SQLite Learner Model（唯一 Source of Truth）
   │
   ├──► ContextSelector（按任务截取）
   │         ▼
   │    TemporalResolver（时间衰减）
   │         ▼
   │    AdaptivePolicy（AdaptiveDecision + reason codes）
   │         ▼
   │    PromptBuilder → LLM → 个性化输出
   │
   └──────────────► 新的用户行为 → 再次闭环
```

## 3. 数据存储分层

| 数据 | 存储 | 说明 |
|---|---|---|
| 长期画像（facts/goals/mastery/ability/preference/misconception/memory） | SQLite `data/learner_model.db` | 唯一真值，支持增删改 |
| 学习事件（历史证据） | SQLite `learning_events` 表 | append-only，与当前状态分离 |
| 画像变更记录 | SQLite `profile_change_log` | 每次增删改可回放、可展示 |
| 画像快照 | SQLite `learner_state_snapshots` | 每累计 N 个事件生成 |
| 短期会话状态 | JSON `data/cache_adaptive-session-*.json` | TTL 1h，不落长期画像 |
| 学习计划/会话历史/知识库 | JSON `data/study_plan.json` 等 | 业务数据，非画像 |

未来迁移生产环境：Repository 接口（`learner_model/repository.py`）可换 PostgreSQL；
Session 可换 Redis；Semantic Memory 可换向量库。**画像逻辑不动**。

## 4. 动态画像闭环

```
LearnerState_t
    → AdaptiveDecision（记录 state_version）
    → 用户学习（讲解/问答/反馈）
    → LearningEvent（SELF_REPORTED_CONFUSION 等）
    → EvidenceExtractor（弱/中/强 × 来源可靠度）
    → 特定 Updater 定向更新（不是整份画像重写）
    → LearnerState_t+1
    → 下一次决策基于新状态
```

禁止：`recent_messages → LLM → 整份 profile 覆盖`。
允许：`Event → Evidence → specific updater → targeted change`。

## 5. 更新速度分层（从快到慢）

```
Session State（即时，不落长期画像）
> KC State（每次有效证据）
> Misconception（重复出现才升，持续正确才降）
> Preference（多次行为积累，用户显式可立即改）
> Ability（慢 EMA，弱证据只计数）
> Stable Profile（极少更新）
```

## 6. Adaptive Engine

- **ContextSelector**：`study_plan` 全课程快照+目标；`topic_tutor` 只取目标 KC+前置+误解+相关能力；
  `adaptive_qa` 先判断学习型问题，非学习型不加载掌握度；`plan_chat` 计划+进度+节奏。
  多课程隔离：所有查询按 `(user_id, course_id)`。
- **TemporalResolver**：`raw_mastery` 不每天重写；使用时算 `recency_days / review_risk / effective_state`
  （mastery=.85 且 180 天无证据 → needs_refresh）。
- **AdaptivePolicy**：策略组件拆分（mastery/confidence/prerequisite/misconception/preference/temporal/ability），
  输出 `AdaptiveDecision`（depth/difficulty/scaffold/pedagogical_actions/delivery_mode/example_count/
  review_or_new/reason_codes/learner_state_version）。
- **PromptBuilder**：把结构化决策转成 LLM 上下文；LLM 不得自行决定教学策略。

## 7. 关键规则

- 弱证据（曝光/理解了）不改变 mastery；mastery 变更只留给未来强证据（外部 assessment）。
- 用户显式声明（`USER_EXPLICIT_*`）优先级最高，可立即覆盖推断偏好。
- Preference 不越积越多：同 key 一条记录，score/confidence 升降、可 inactive/reactivate。
- Misconception 有生命周期：candidate → active → resolving → resolved（可 reactivate）。
- 用户删除 Fact/Memory：真正 DELETE，change log 只留最小审计。
