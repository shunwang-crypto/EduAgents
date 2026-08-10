# Evidence 模型（事件 → 证据 → 状态变更）

## 三层追踪

```
learning_events（append-only 历史）
      ↓ extract_evidence
learner_evidences（结构化证据，带 provenance，幂等唯一键）
      ↓ updaters
learner_* 状态表（当前画像）
      ↓
profile_change_log（before/after 变更记录）
```

## Evidence 字段

`learner_evidences`：`evidence_id` / `event_id` / `event_type` / `user_id` / `course_id` /
`kc_id` / `entity_type`(knowledge|preference|misconception|profile_fact|goal|ability|behavior) /
`entity_key` / `direction`(pos|neg|neutral) / `weight`(strength×reliability) /
`source`(USER_EXPLICIT > EXTERNAL_ASSESSMENT > TEACHING_INTERACTION > SYSTEM_OBSERVATION >
BEHAVIOR_INFERENCE > LLM_INFERENCE) / `classifier_version` / `confidence` / `payload_json`

幂等：`(event_id, entity_type, entity_key, classifier_version)` 唯一 —— 同一事件重放不重复强化。

## 证据来源

| 来源 | 事件 | 强度 | 作用 |
|---|---|---|---|
| 规则 | `EXPLANATION_DELIVERED` 等 | weak | 只更新曝光时间/计数 |
| 规则 | `SELF_REPORTED_UNDERSTANDING/CONFUSION` | weak | 只微调 confidence |
| 规则 | `EXAMPLE_REQUESTED/ANALOGY_REQUESTED` | medium | 偏好强化 |
| 规则 | `FEEDBACK_GIVEN` | medium | 按 delivery_mode 调偏好有效性 |
| 语义分类 | `CHECK_UNDERSTANDING_RESPONSE` 等（高信息量事件） | medium | 能力/误解/知识（强证据才小幅初始化 mastery） |
| 显式 | `USER_EXPLICIT_*` | strong | 直接设置，最高优先级 |

## Semantic Evidence Classifier（`evidence/semantic_classifier.py`）

- 只产出 **Evidence Candidate**，绝不直接改画像数值。
- **高确定规则**（无模型也能跑）：
  - 普通提问（"为什么 Attention 要除以 sqrt(dk)？"）**不**判为 misconception；
  - 只有明确自述混淆（"我一直以为 X 是 Y"、"总是搞混 X 和 Y"）才创建 misconception candidate；
  - 学生用自己的话解释概念（含机制词）→ 正能力证据（understanding/reasoning/expression）。
- `LEARNER_MODEL_SEMANTIC_INFERENCE_ENABLED=true` 时额外启用 LLM 扩展（同样只出 Candidate）。

## 强证据与 Mastery

`CHECK_UNDERSTANDING_RESPONSE`（medium+，用户自述理解）是当前唯一允许小幅初始化/更新 mastery 的
证据：首次保守初始 0.3，后续单次变化 ≤0.1，绝不凭一句"懂了"给出高分。
其余（曝光/理解了/困惑）一律不改 mastery。
