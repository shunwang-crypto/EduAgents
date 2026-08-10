# LearnerState v1 对接模板

这套文件用于定义“合作伙伴学习者画像系统 → EduAgents”的数据边界。

## 一、文件结构

```text
user/
├── profile.json
├── goals.json
├── preferences.json
├── semantic_memory.md
├── events.jsonl
└── courses/
    └── java-oop/
        └── learner_state.json
```

如果用户学习多门课程，只新增对应课程目录：

```text
courses/
├── java-oop/learner_state.json
├── transformer/learner_state.json
└── operating-system/learner_state.json
```

因此逻辑上是：

- 5 份用户级数据
- N 份课程级 Learner State

正式生产环境不要求真的按文件保存；这些文件主要用于确定字段和接口协议。最终可以映射为 PostgreSQL / Redis / Qdrant。

---

## 二、各文件职责

### 1. profile.json
用户相对稳定的信息。

应该包含：
- user_id
- display_name
- education_level
- language
- background

不要包含：
- 某门课程 mastery
- weak topics
- 当前课程进度

---

### 2. goals.json
用户所有当前/历史学习目标。

每个目标必须至少关联：
- goal_id
- course_id
- target / goal_name
- progress
- status

一个用户可以同时存在多个 active goals。

---

### 3. preferences.json
跨课程、相对长期的学习偏好或教学方式效果。

建议包含：
- preferred_mode
- learning_style_distribution
- pace_factor
- scaffold_preference
- mode_effectiveness

重要：
不要只保存永久标签，例如“视觉型学习者”。
更推荐保存某种教学方式在历史中的实际效果、置信度和样本量。

---

### 4. semantic_memory.md
给 LLM 检索的长期语义记忆。

适合：
- 学习经历
- 项目背景
- 曾经有效的类比
- 长期稳定的解释偏好

不适合：
- mastery=0.63
- ability=0.42

精确状态必须在结构化 Learner State 中保存。

---

### 5. events.jsonl
原始学习证据，推荐 append-only。

每条事件至少应带：
- event_id
- event_type
- user_id
- course_id
- goal_id（如适用）
- kc_id（如适用）
- timestamp
- payload

典型事件：
- TOPIC_STARTED
- TOPIC_COMPLETED
- QUESTION_ASKED
- EXPLANATION_REQUESTED
- EXPLANATION_DELIVERED
- RESOURCE_OPENED
- PLAN_CREATED
- PLAN_STEP_COMPLETED
- FEEDBACK_GIVEN
- ASSESSMENT_RESULT（若由其他系统提供）

EduAgents 可以产生事件，但不要直接修改合作伙伴维护的长期画像真值。

---

### 6. courses/<course_id>/learner_state.json
这是最重要的课程级学习者状态。

应该包含：

#### Knowledge State
每个 KC 至少：
- mastery
- confidence
- trend
- evidence_count
- last_evidence_at
- is_estimated

现有系统只有 mastery 数值时，其他字段先填 null，不要虚构。

#### Ability State
六维能力建议保留：
- understanding
- application
- reasoning
- expression
- reflection
- transfer

每一维建议至少：
- score
- confidence
- trend
- evidence_count

班级平均只用于 Dashboard 展示，不建议作为 EduAgents 自适应决策的核心输入。

#### Misconception
不要只停留在 `mixed×7`。
目标结构应逐步细化成：
- kc_id
- misconception_id
- type
- description
- severity
- confidence
- occurrence_count
- status
- evidence ids / timestamps

#### Behavior
可放当前课程相关：
- activity_count_30d
- streak_days
- recent_topics
- frequent_revisited_topics

---

## 三、当前这份数据已经能直接填的内容

当前同学给出的画像可直接映射：

- 林同学
- Java 面向对象程序设计实训
- GOAL-JAVA-001
- 成绩管理实训
- 进度 31%
- 总掌握度 31%
- 已掌握 4/7
- 本月学习 87 次
- 连续 1 天
- 7 个 KC mastery
- 六维能力
- 班级平均
- example_driven
- visual=0.30
- reading=0.35
- mixed×7
- 当前成长轨迹均 is_estimated=true

模板中未知字段全部使用 `null`，没有人为编造。

---

## 四、目前最需要合作伙伴补的字段

### Knowledge State
- confidence
- trend
- evidence_count
- last_evidence_at
- is_estimated（逐 KC）

### Ability
- confidence
- evidence_count
- trend

### Preference
- mode_effectiveness
- confidence
- sample_size
- pace_factor
- scaffold_preference

### Misconception
把 `mixed×7` 细化到具体 KC 和具体错误认知。

### History
把当前全部 `is_estimated=true` 的成长轨迹逐步替换为真实事件驱动的 mastery history。

---

## 五、不要放进 Learner State 的内容

以下属于 EduAgents Adaptive Engine，不属于画像本身：

- 下一步先学哪个知识点
- 补救顺序
- 学习路径
- 教学策略
- 本轮讲多深
- 是否先讲前置知识
- 本轮使用案例 / 类比 / 分步讲解
- 时间怎么分配
- 资源推荐排序

例如：

`ENCAPSULATION mastery = 0.0`

是 Learner State。

“因此下一步优先学习封装”

是 EduAgents 的 Adaptive Decision。

---

## 六、建议双方最终接口

用户级：

```text
GET /api/v1/learners/{user_id}
```

返回：
- profile
- preferences
- active_goals

课程级：

```text
GET /api/v1/learners/{user_id}/courses/{course_id}/state
```

返回：
- progress
- knowledge
- abilities
- misconceptions
- behavior
- metadata

事件写入：

```text
POST /api/v1/learners/{user_id}/events
```

EduAgents 将学习交互作为 evidence 发回；合作伙伴决定如何更新 Learner Model。

---

## 七、双方职责

### 合作伙伴
负责：
- Learner Modeling
- Profile
- Mastery
- Confidence
- Ability
- Misconception
- Preference
- Behavior State
- Evidence aggregation
- Learner State 更新和持久化

### EduAgents
负责：
- 读取 Learner State
- Context Selection
- KC / prerequisite / KST-lite
- Temporal Resolver
- Adaptive Policy
- 学习计划
- 个性化知识讲解
- 个性化学习问答
- Prompt Builder
- 产生新的 Interaction Events

一句话：

**合作伙伴维护“学生现在是什么状态”，EduAgents 决定“面对这个状态现在应该怎么学、怎么教”。**
