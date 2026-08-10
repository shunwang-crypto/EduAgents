# EduAgents — 自适应学习引擎

EduAgents 是一个**基于外部动态学习者模型（LearnerState）的自适应学习规划与个性化辅导系统**。

它**不负责学习者画像建模，也不实现练习/测验系统**，而是回答一个核心问题：

> 合作伙伴 Learner Model 告诉我"这个学生现在是什么状态"；
> EduAgents 负责决定"面对这个学生，现在应该怎么学、怎么教"。

## 核心定位

```
合作伙伴 Learner Model（LearnerState 的唯一 Source of Truth）
        │ LearnerState API
        ▼
LearnerStateProvider（mock / remote）
        │ Adapter（容忍字段变化）
        ▼
LearnerState（内部契约）
        │
   ┌────┴────────────┐
   ▼                 ▼
Domain Model      Session State
KC Graph / KST-lite  （Redis 或本地 JSON）
        │                 │
        └───────┬─────────┘
                ▼
         Context Selector（按任务只选相关状态）
                ▼
         Temporal Resolver（掌握度时间衰减）
                ▼
         Adaptive Policy（规则式教学决策 + reason codes）
                ▼
          Prompt Builder（结构化 → LLM 上下文）
                ▼
     Study Plan / Topic Tutor / Adaptive QA / Plan Chat
                ▼
              LLM → 个性化输出
                ▼
         Interaction Event → Outbox → 合作伙伴
                ▼
            合作伙伴更新 LearnerState → 下一轮
```

## 已删除的业务

- ❌ Quiz / Practice / 练习生成 / 练习设计
- ❌ 错题 / 答题 / 自动判分 / 错题反思
- ❌ 本地 student_profile 推断（第二套画像引擎）
- ❌ 本地 mastery ±delta 变更

EduAgents 只 **读取** LearnerState、**决策**、**Emit Evidence**；数值更新归合作伙伴。

## 功能

- **自适应学习计划**：读 LearnerState → KC Graph（前置链）→ 跳过已掌握、优先前置缺失、按目标安排顺序
- **自适应专题讲解**：按目标 KC 掌握度/置信度/误解/偏好决定深度、脚手架、教学模式
- **自适应知识问答**：学习型问题映射 KC → 注入画像上下文；非学习型问题不加载画像
- **计划问答 / 计划调整**：结合当前计划 + 画像节奏动态调整
- **Learner State 只读面板**：掌握度/能力/误解/偏好/行为/版本/新鲜度
- **多课程隔离**：Java 请求不加载 Transformer mastery（key 均为 user_id + course_id）
- **Learning Event 回传**：用户行为 → Outbox（幂等）→ 异步投递合作伙伴

## 技术栈

Streamlit · LangChain · langchain-openai · Pydantic · python-dotenv · pytest

## 项目结构

```text
EduAgents/
├─ app/streamlit_app.py
├─ src/edu_agent/
│  ├─ adaptive/                 # 自适应引擎
│  │  ├─ schemas.py             # SelectedContext / AdaptiveDecision / reason codes
│  │  ├─ context_selector.py    # 按任务类型只选相关 LearnerState
│  │  ├─ temporal_resolver.py   # 掌握度时间衰减（recency / review_risk）
│  │  ├─ policy.py              # 规则式策略（mastery/confidence/prereq/misconception/preference/temporal）
│  │  ├─ prompt_builder.py      # 结构化决策 → LLM 上下文
│  │  └─ service.py             # 一键流水线（读状态→选上下文→决策→prompt）
│  ├─ integrations/
│  │  └─ learner_state/         # LearnerState Provider 层
│  │     ├─ schemas.py          # 内部 LearnerState 契约
│  │     ├─ adapter.py          # 合作伙伴原始 JSON → 内部模型
│  │     ├─ provider.py         # Provider 接口 + 工厂
│  │     ├─ mock_provider.py    # Java OOP 演示数据
│  │     ├─ remote_provider.py  # HTTP 访问 + 缓存 + 降级
│  │     └─ event_emitter.py    # LearningEvent / Outbox / 投递
│  ├─ domain/kc_graph.py        # Course / KC / 关系 + KST-lite（reachable frontier）
│  ├─ workflows/                # study_plan / topic_tutor / kb_qa / plan_chat
│  ├─ tools/                    # course_kb / kb_store / github_importer / web_search / app_state_store
│  ├─ core/llm.py               # 多模型 fallback
│  └─ router/workflow_router.py
├─ tests/                       # 架构契约 / provider / adapter / policy / event 等
└─ docs/
   ├─ adaptive-learning-architecture.md
   ├─ learner-state-contract.md
   ├─ learning-events.md
   └─ migration-from-legacy.md
```

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env        # 配置 OPENAI_* 或 XINGCHEN_*；LearnerState 默认 mock
streamlit run app/streamlit_app.py
```

未配置 `LEARNER_STATE_BASE_URL` 时默认使用 **Mock LearnerStateProvider**（Java OOP 演示数据），开箱即可体验完整自适应链路。

## 测试

```bash
pytest tests/ -v
```

测试覆盖：LearnerState schema / adapter / provider 降级 / 多课程隔离 / Context Selector / Adaptive Policy（mastery 差异、confidence 区分、前置触发复习、误解改变动作、时间衰减）/ Event 幂等与可靠性 / 架构契约（无本地 mastery 变更、无练习系统残留、个性化差异）。
