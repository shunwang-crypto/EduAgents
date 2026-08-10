# LearnerState v1 契约

本目录是 **EduAgents ↔ 合作伙伴 Learner Model** 的对接契约与示例（Contract / Example / Mock reference / 联调文档）。

## ⚠️ 重要声明

`examples/` 下的 JSON 仅用于：

- Contract（字段约定）
- Example（示例形态）
- Mock reference（Mock Provider 的参考）
- 联调文档

**绝对不是生产运行时画像的 Source of Truth。**

生产业务代码禁止直接读取 `docs/contracts` 下的 JSON 作为真实用户画像。

## 真实画像数据流

```
合作伙伴 Learner Model（唯一 Source of Truth：PostgreSQL + Redis）
        │ HTTP API
        ▼
LearnerStateProvider（remote / mock）
        │ Adapter
        ▼
内部 LearnerState（只读消费，EduAgents 不落长期真值）
```

- 长期画像 → 合作伙伴数据库
- LearnerState 缓存 / Session State → EduAgents Redis（带 TTL，非真值）
- Adaptive Decision Log / Learning Events / Outbox → EduAgents PostgreSQL

## 目录

```
learner-state-v1/
├── README.md
└── examples/
    ├── profile.json              用户级 Profile 示例
    ├── goals.json                目标列表示例
    ├── preferences.json          偏好示例（mode_effectiveness）
    ├── events.jsonl              学习事件示例（每行一个事件）
    ├── semantic_memory.md        语义记忆示例
    └── courses/
        └── java-oop/
            └── learner_state.json 课程级 LearnerState 示例
```

## 关键约定

- `mastery` 与 `confidence` 分离：`mastery=.20 + confidence=.95` 表示基本确定不会；`confidence=.15` 表示数据不足。
- 所有课程请求必须带 `user_id + course_id`（必要时 `goal_id`），多课程隔离。
- 未知字段保持 `null`，禁止编造。
