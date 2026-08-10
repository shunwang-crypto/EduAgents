# Learning Events（本地证据闭环）

> 事件是「发生过什么」（历史，append-only）；画像状态是「系统当前认为什么」（可增删改）。
> 两者严格分离。

## 事件类型（V1）

会话/课程：`SESSION_STARTED` `SESSION_ENDED` `COURSE_OPENED`
目标：`GOAL_CREATED` `GOAL_UPDATED` `GOAL_COMPLETED` `GOAL_CANCELLED`
主题/计划：`TOPIC_STARTED` `TOPIC_COMPLETED` `TOPIC_REVISITED`
`PLAN_CREATED` `PLAN_UPDATED` `PLAN_STEP_STARTED` `PLAN_STEP_COMPLETED`
问答：`QUESTION_ASKED` `EDUCATIONAL_QUESTION_ASKED`
讲解：`EXPLANATION_REQUESTED` `EXPLANATION_DELIVERED` `RE_EXPLAIN_REQUESTED`
`EXAMPLE_REQUESTED` `ANALOGY_REQUESTED` `SIMPLIFICATION_REQUESTED` `DEEPER_EXPLANATION_REQUESTED`
`PREREQUISITE_REVIEWED` `RESOURCE_OPENED` `RESOURCE_COMPLETED`
反馈：`SELF_REPORTED_UNDERSTANDING` `SELF_REPORTED_CONFUSION` `FEEDBACK_GIVEN`
显式声明：`USER_EXPLICIT_PREFERENCE` `USER_EXPLICIT_PROFILE_FACT` `PROFILE_FACT_DELETED`
其它：`TEACHING_MODE_SWITCHED`

## 证据强度与来源可靠度

```
evidence_strength: weak | medium | strong
source_reliability: USER_EXPLICIT(1.0) > EXTERNAL_ASSESSMENT(0.95)
                    > TEACHING_INTERACTION(0.7) > SYSTEM_OBSERVATION(0.6)
                    > BEHAVIOR_INFERENCE(0.4) > LLM_INFERENCE(0.3)
```

原则：**用户明确声明 > 可靠正式数据 > 重复行为 > LLM 语义推断 > 单次行为**。

## 证据示例

| 事件 | 强度 | 对画像的作用 |
|---|---|---|
| `EXPLANATION_DELIVERED` | weak | 只更新 last_evidence_at / evidence_count，**不改 mastery** |
| `SELF_REPORTED_UNDERSTANDING` | weak | 只微升 confidence，不改 mastery |
| `SELF_REPORTED_CONFUSION` | weak | 困惑信号：微降 confidence；可触发 misconception 候选 |
| `EXAMPLE_REQUESTED` | weak | `worked_example` 偏好 score/confidence 小幅上升 |
| `SIMPLIFICATION_REQUESTED` | medium | `step_by_step` 偏好上升 + 需要辅导信号 |
| `USER_EXPLICIT_PREFERENCE` | strong | 直接设置/纠正偏好，confidence=0.9 |
| `USER_EXPLICIT_PROFILE_FACT` | strong | 创建/更新事实（同 key 不重复追加） |
| `PROFILE_FACT_DELETED` | strong | 真正删除事实 |

## 闭环

```
行为 → build_event() → apply_event()
                        ├── record_event（append-only 入库）
                        ├── extract_evidence（规则 + 可选 LLM 候选）
                        ├── 各 Updater 定向更新
                        ├── profile_change_log 记录
                        └── state_version +1（有变更时）；每 N 事件生成快照
```

## LLM 的边界

LLM（若启用 `LEARNER_MODEL_LLM_INFERENCE_ENABLED=true`）只从自由文本产出
**Evidence Candidate**（如"可能有 static_type_dynamic_type_confusion"）；
最终是否创建/强化 misconception 由 Updater 规则决定。
**禁止 LLM 直接重写整份画像。**
