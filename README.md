# EduAgents — 自适应学习规划与个性化辅导系统

> 具有**本地动态学习者模型**（SQLite）的自适应学习系统。
> 回答两个问题：**这个学生现在是什么状态？**（Learner Model）
> **面对这个状态，现在应该怎么学、怎么教？**（Adaptive Engine）

## 核心架构

```
用户行为（提问 / 请求讲解 / 反馈 / 完成计划）
        │
        ▼
   LearningEvent（append-only 历史证据）
        │
        ▼
   EvidenceExtractor（事件 → 结构化证据）
        │
        ▼
   Updaters（knowledge / preference / misconception / ability / fact / goal / memory）
        │
        ▼
   SQLite Learner Model（data/learner_model.db · 唯一画像真值）
        │
        ▼
   Context Selector（按任务只选相关状态）
        │
        ▼
   Temporal Resolver（掌握度时间衰减）
        │
        ▼
   Adaptive Policy（结构化教学决策 + reason codes）
        │
        ▼
   Prompt Builder → LLM → 个性化输出
        │
        └──────────────→ 新的用户行为 → 再次闭环
```

## 两个核心部分

### A. Dynamic Learner Model（`src/edu_agent/learner_model/`）

本地 SQLite 维护完整学习者画像，支持完整生命周期：

- **CREATE / UPDATE / REINFORCE / WEAKEN / DEACTIVATE / REACTIVATE / RESOLVE / DELETE**
- Preference 能升能降（`worked_example .82 → .68`）
- Misconception 能出现也能解决（`candidate → active → resolving → resolved`）
- Profile Fact 同 key 只保留一条（冲突 UPDATE 而非追加）
- 用户明确删除 → 真正 DELETE（change log 只留最小审计，不存被删内容副本）
- Events（历史）与 Learner State（当前结论）严格分离

数据表（12 张）：`learners` / `learner_profile_facts` / `learning_goals` /
`learner_course_states` / `learner_kc_states` / `learner_abilities` /
`learner_preferences` / `learner_misconceptions` / `learner_semantic_memories` /
`learning_events` / `learner_evidences` / `profile_change_log` / `learner_state_snapshots` /
`adaptive_decisions` / `domain_courses` / `domain_kcs` / `domain_kc_relations`

### B. Adaptive Engine（`src/edu_agent/adaptive/`）

- **ContextSelector**：不同任务（学习计划/专题讲解/问答/计划问答）只挑选相关状态，多课程隔离（`user_id + course_id`）
- **TemporalResolver**：掌握度是时间函数（`mastery=.85`，180 天无证据 → `needs_refresh`）
- **AdaptivePolicy**：规则式教学决策（mastery/confidence/prerequisite/misconception/preference/temporal/ability 策略组件拆分），输出结构化 `AdaptiveDecision` + 可解释 `reason_codes`
- **PromptBuilder**：策略先于 LLM —— LLM 只执行教学策略，不自行决定个性化

## 关键原则

- **不维护第二套画像**：SQLite Learner Model 是唯一真值，无 student_profile / 旧 mastery ±delta
- **无 Quiz / Practice / Mistake 业务**：只做教学讲解与检查理解，不做练习系统
- **UNKNOWN ≠ 0**：从未观察的 mastery/ability 是 NULL（未知），与「确认不会」严格区分；
  Adaptive Policy 对 UNKNOWN 走中性首次教学（`UNKNOWN_KNOWLEDGE_STATE`），不武断说"你不会"
- **弱证据保守**：`EXPLANATION_DELIVERED` 只更新曝光时间，`SELF_REPORTED_UNDERSTANDING` 只微调
  confidence，绝不跳 mastery；只有强证据（理解检查语义分类）才允许小幅初始化/更新 mastery（≤0.3/≤0.1 每次）
- **用户显式声明 > 模型推断**：`USER_EXPLICIT_*` 事件优先于行为推断
- **多课程隔离**：所有状态 `(user_id, course_id)` 隔离；全局/课程双版本；`LearningContext + CourseResolver`
  保证任意学习主题建立独立 course_id（不是全落 JAVA-OOP）；自定义课程 Domain Model 持久化跨重启
- **事件/证据/状态三层**：`learning_events`（append-only）→ `learner_evidences`（幂等 provenance）→
  画像状态；`profile_change_log` 保存真实 before/after；用户删除敏感数据只留最小审计
- **事务与幂等**：事件→证据→状态→版本→快照单事务；同一 event_id 重放不重复应用
- **不依赖任何外部画像服务**：无 Partner API / Remote Provider / 事件回传网关

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env       # 配置 LLM key（或留空走演示模式）
streamlit run app/streamlit_app.py
```

首次使用会在 `data/learner_model.db` 自动建库；新用户无画像时系统正常运转（不编造默认值），
用户填写背景/目标/偏好后产生 `USER_EXPLICIT_*` 事件形成初始画像。

## 目录结构

```
src/edu_agent/
├── learner_model/          # 本地动态学习者模型（SQLite）
│   ├── db.py               # 连接 + DDL
│   ├── repository.py       # 抽象接口（未来可换 PostgreSQL）
│   ├── sqlite_repository.py
│   ├── service.py          # 业务门面（事件闭环/画像操作）
│   ├── change_log.py       # 画像变更记录
│   ├── snapshot.py         # 画像快照
│   ├── evidence/           # 事件 → 证据
│   └── updaters/           # 定向更新器（knowledge/ability/preference/...）
├── adaptive/               # 自适应引擎（Context/Temporal/Policy/Prompt）
├── domain/learning/        # KC Graph / KST-lite（所有用户共享）
├── workflows/              # study_plan / topic_tutor / kb_qa / plan_chat
└── tools/                  # 知识库 / 状态存储等
```

## 测试

```bash
pytest tests/ -v
```

覆盖：SQLite 仓库 CRUD、事件 append-only、画像生命周期（fact/preference/misconception）、
弱证据保守更新、用户显式覆盖、删除不留副本、多课程隔离、时间衰减、
上下文选择差异、策略差异、闭环（Event→State→Decision）、无 partner/quiz 残留契约。
