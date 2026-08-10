# 存储架构

## 总原则：数据存哪里，由"谁是真值"决定

| 数据 | 存储 | 角色 |
| -- | -- | -- |
| 长期 LearnerState（Profile/Mastery/Ability/Misconception/Preference/Behavior/历史） | **合作伙伴数据库** | 唯一 Source of Truth |
| LearnerState 缓存 | EduAgents Redis（`learner-state:{user_id}:{course_id}`，带 TTL） | 非真值，可过期 |
| Session State | EduAgents Redis（`adaptive-session:{user_id}:{course_id}:{session_id}`，TTL） | 短期状态 |
| Study Plans / Plan Progress / Domain Model | EduAgents PostgreSQL | EduAgents 自有业务 |
| Adaptive Decision Log | EduAgents PostgreSQL | 调试/实验/论文 |
| Learning Events / Event Outbox | EduAgents PostgreSQL | 待回传证据 |
| Semantic Memory | Qdrant | 长期语义记忆（用户经历/有效类比） |
| `docs/contracts/learner-state-v1/` | 仓库文档 | Contract / Example / Mock reference，**不是生产真值** |
| `src/edu_agent/adaptive/` | 代码 | 自适应算法（不存数据真值） |

## EduAgents Redis Keys

```
learner-state:{user_id}:{course_id}                     # LearnerState 缓存（fresh/stale/mock/missing）
adaptive-session:{user_id}:{course_id}:{session_id}     # 会话状态（re_explain_count 等）
```

原型实现：`data/cache_learner-state-*.json`、`data/cache_adaptive-session-*.json`（接口可替换 Redis）。

## EduAgents PostgreSQL 表（生产）

- `plans` / `plan_steps` / `plan_progress`
- `courses` / `knowledge_components` / `kc_relations`（Domain Model，所有用户共享）
- `adaptive_decisions`（decision_id / user_id / course_id / goal_id / session_id / task_type / target_kc / learner_state_version / state_freshness / selected_context_json / temporal_state_json / decision_json / reason_codes / policy_version / created_at）
- `learning_events` / `learning_event_outbox`（event_id 幂等 / delivery_status / retry_count）

## Qdrant

只存 Semantic Memory（"用户通过 Java interface 理解 Python Protocol"之类），禁止存 `mastery=.63` 精确数值。

## 禁止

- EduAgents 不把合作伙伴 LearnerState 永久保存为第二套真值
- 不创建 `session_state.json` 作为长期状态（Session 用 Redis 语义，过期即弃）
- 不读取 `docs/contracts` 下 JSON 作为真实用户画像
