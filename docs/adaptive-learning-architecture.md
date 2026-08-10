# 自适应学习架构

## 1. 分层职责

| 层 | 模块 | 职责 |
| -- | -- | -- |
| 外部状态 | 合作伙伴 Learner Model | LearnerState 唯一 Source of Truth（profile/goals/preferences/mastery/ability/misconception/behavior） |
| Provider 层 | `integrations/learner_state/` | 业务层唯一访问入口；mock / remote；缓存与降级 |
| 适配层 | `adapter.py` | 合作伙伴原始 JSON → 内部契约；字段变化只改这里 |
| 领域层 | `domain/kc_graph.py` | 课程知识结构（KC + 关系 + KST-lite） |
| 会话层 | Session State | 可立即变化的短时状态（当前 KC、re_explain 次数等） |
| 决策层 | `adaptive/` | Context Selector → Temporal Resolver → Policy → Prompt Builder |
| 业务层 | `workflows/` | Study Plan / Topic Tutor / Adaptive QA / Plan Chat |
| 回传层 | `event_emitter.py` | LearningEvent → Outbox → 异步投递合作伙伴 |

## 2. 数据流

```
LearnerState_t
  ↓ Read（Provider + Adapter + Cache）
Diagnose（Context Selector：只选相关 KC/前置/误解/能力/偏好）
  ↓
Decide（Temporal Resolver + Adaptive Policy → AdaptiveDecision + reason_codes）
  ↓
Teach（Prompt Builder → LLM → 个性化输出）
  ↓
Observe（用户行为）
  ↓
Emit Evidence（LearningEvent → Outbox）
  ↓
Partner Update（合作伙伴刷新 LearnerState）
  ↓
LearnerState_t+1 → 下一轮
```

## 3. Context Selector：按任务类型选上下文

- `study_plan`：Goal + 目标 KC + 全课程掌握度快照 + 能力 + 偏好 + 进度
- `topic_tutor`：目标 KC + 传递前置 + 误解 + understanding/application/expression + 偏好
- `adaptive_qa`：学习型问题映射 KC 后同上；非学习型问题只带基础偏好
- `plan_chat`：计划 + 进度 + 弱 KC + 节奏

**多课程隔离**：所有 key 都是 `user_id + course_id`；Java 请求绝不会加载 Transformer mastery。

## 4. Temporal Resolver

```
raw_mastery=.82, last_evidence_at=120 天前
  → recency_days=120, review_risk=high, effective_state=needs_refresh
raw_mastery=.82, last_evidence_at=2 天前
  → recency_days=2, review_risk=low, effective_state=mastered
```

V1 为可解释规则；接口保留升级为复杂遗忘模型的空间。

## 5. Adaptive Policy

规则式基线，策略组件拆分（非 1000 行 if/else）：

| 组件 | 输入 → 输出 |
| -- | -- |
| mastery_policy | mastery → depth / difficulty / scaffold / 基础动作 |
| confidence_policy | confidence<0.5 → 保守 + CHECK_UNDERSTANDING |
| prerequisite_policy | 目标前置链未掌握 → REVIEW_PREREQUISITE + prerequisite_topics |
| misconception_policy | active 误解 → CONCEPT_COMPARISON + COUNTEREXAMPLE |
| temporal_policy | review_risk 高 → review_or_new=review |
| preference_policy | Pedagogical Need > Task Suitability > User Preference |

输出始终带 `reason_codes`（如 `LOW_PREREQUISITE_MASTERY`），可解释、可调试、可做实验对比。

教学动作固定集合：`EXPLAIN / WORKED_EXAMPLE / PARTIAL_EXAMPLE / HINT / ANALOGY / COUNTEREXAMPLE / REVIEW_PREREQUISITE / SUMMARIZE / CONCEPT_COMPARISON / DECOMPOSE / SIMPLIFY / DEEPEN / CHECK_UNDERSTANDING / SOCRATIC_QUESTION`。**不包含任何练习/测验动作。**

## 6. 降级策略

Partner API 不可用：

1. 尝试 Remote；
2. 有可接受缓存 → 用缓存并标记 `stale`；
3. 无缓存 → Mock 数据标记 `mock`（或空状态 `missing`）；
4. 业务输出仍然可用，上下文标注 `state_freshness`。

## 7. 与主项目（FastAPI/Next.js/PostgreSQL/Redis/Qdrant）的关系

本仓库为 Streamlit 原型实现。Provider / Outbox 接口按生产可替换设计：

- `LearnerStateProvider` → 生产可换成 Redis 缓存 + 服务发现；
- Session State → 当前用本地 JSON（`app_state_store` 动态 key），生产换 Redis（`learner-session:{user_id}:{course_id}`，TTL）；
- Outbox → 当前为 JSON 文件，生产复用 Worker + 指数退避 + `event_id` 幂等。
