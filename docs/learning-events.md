# Learning Events

## 1. 原则

EduAgents **只 Emit Evidence，不直接改长期画像数值**：

```
错误：if user_says_understood: mastery += 0.2     ❌ 禁止
正确：emit_event("SELF_REPORTED_UNDERSTANDING", evidence_strength="weak")   ✅
```

数值更新由合作伙伴 Learner Model Updater 完成。

## 2. 事件结构（`LearningEvent`）

```json
{
  "schema_version": 1,
  "event_version": 1,
  "event_id": "uuid",
  "event_type": "EXPLANATION_REQUESTED",
  "user_id": "STU-001",
  "course_id": "JAVA-OOP",
  "goal_id": "GOAL-JAVA-001",
  "kc_id": "POLYMORPHISM",
  "session_id": "...",
  "timestamp": "...",
  "source": "edu_agent",
  "evidence_strength": "weak|medium|strong",
  "meaningful_for_profile": true,
  "payload": {},
  "metadata": {}
}
```

## 3. 事件类型（V1）

SESSION_STARTED / SESSION_ENDED / COURSE_OPENED / TOPIC_STARTED / TOPIC_COMPLETED
QUESTION_ASKED / EDUCATIONAL_QUESTION_ASKED / EXPLANATION_REQUESTED / EXPLANATION_DELIVERED
RE_EXPLAIN_REQUESTED / EXAMPLE_REQUESTED / ANALOGY_REQUESTED / SIMPLIFICATION_REQUESTED
DEEPER_EXPLANATION_REQUESTED / PREREQUISITE_REVIEWED / RESOURCE_OPENED / RESOURCE_COMPLETED
PLAN_CREATED / PLAN_UPDATED / PLAN_STEP_STARTED / PLAN_STEP_COMPLETED
SELF_REPORTED_UNDERSTANDING / SELF_REPORTED_CONFUSION / TEACHING_MODE_SWITCHED
FEEDBACK_GIVEN / GOAL_CREATED / GOAL_UPDATED / GOAL_COMPLETED

## 4. 证据强度

| 强度 | 事件示例 | 说明 |
| -- | -- | -- |
| weak | RESOURCE_OPENED / SELF_REPORTED_UNDERSTANDING / TOPIC_COMPLETED | "懂了"不能 mastery .2→.8 |
| medium | 自主解释概念 / 理解检查通过 / 连续完成任务 | 可适度更新 |
| strong | 外部 assessment / 代码任务结果 / 教师评价 | 可大幅更新 |

## 5. 可靠性

- 事件先写 **Outbox**（本地 JSON，`event_id` 幂等去重）；
- 后台 `flush_outbox()` 投递合作伙伴，失败保留 + 指数退避重试；
- 合作伙伴 API 不可用**绝不阻塞用户主请求**；
- `meaningful_for_profile`：区分 PAGE_OPENED（false）与 RE_EXPLAIN_REQUESTED（true）。

## 6. 闭环

```
Read → Diagnose → Decide → Teach → Observe → Emit Evidence
→ Partner Update → Read Again
```

最终一致性：不依赖"刚发事件就立刻同步得到新版画像"。
