# EduAgents 架构

## 产品范围

EduAgents 只提供三个用户可见核心能力：

1. **我的课程** — 创建 / 查看 / 切换 / 重命名 / 删除课程，并按用户自己创建的**课程分类**（Category）整理
2. **学习计划** — 每门课程一个个性化学习计划（目标 / 阶段 / 步骤 / 状态）
3. **普通 AI 对话** — 无课程普通对话，或带当前课程上下文的对话

后台保留轻量 **Dynamic Learner Model**（SQLite），用于让学习计划更贴合用户背景、让对话更个性化。
**不提供**：今日学习、最近学习、学习画像页面、Topic Tutor、KB QA、Quiz/Practice/Grading/Assessment/Mistake、排行榜等任何复杂教育平台功能（练习/评测属于外部 Practice 模块职责，本模块仅提供 Handoff 接口）。

## 课程分类（Course Categories）

**Category 只是纯组织层**：把用户自己创建的课程分组整理（Python / Java / AI / 工作技能…）。

- 系统**不自动创建子课程**、不按课程名自动分类（绝不 `if "python" in title`）、不生成 Module / 课程树 / DAG；分类完全由用户决定，创建后 0 门课程也是合法状态。
- Category **不拥有** mastery / KC / goal / learner state / semantic memory / study plan / progress / RAG / sources / conversation / evidence 中的任何一项；所有 Adaptive 数据继续严格绑定 `(user_id, course_id)`。
- **删除分类** = 分类下课程 `category_id` 置 NULL（移到未分类），课程与全部 Adaptive 数据（Goal / KC / Mastery / Memory / Plan / Sources / Conversations / Lessons / Progress）一律不动；**重命名分类**只改 `course_categories.name`。
- 「未分类」是前端 pseudo-category（`category_id = null`），不是数据库行。

## 技术栈

- 后端：FastAPI + SQLite（WAL）+ Pydantic
- LLM：可选（core/llm.py 有回退逻辑；无模型时工作流降级为确定性输出）
- RAG：可选（tools/course_kb.py，课程资料检索，作为 Chat 内部能力）
- 前端：React + TypeScript + Vite（frontend/），ChatGPT 式 Sidebar + Main

## 分层

```
Frontend (React)
    ↓  HTTP
FastAPI (src/edu_agent/api)
    ↓
Application Services (src/edu_agent/application)
    ├─ CourseService
    ├─ CourseCategoryService（纯组织层 CRUD；零 Adaptive 语义）
    ├─ StudyPlanService
    ├─ ChatService
    └─ LearningContextService
    ↓
Core (src/edu_agent/core, domain/learning, adaptive/, workflows/study_plan)
    ├─ Learner Model (learner_model/ — SQLite 唯一画像真值)
    ├─ Plan Context / Chat Context（画像 → 提示词的轻量选择器）
    ├─ Study Plan Workflow（唯一 workflow）
    ├─ Course Domain Model（内置只读模板 kc_graph + user_courses）
    └─ LLM / RAG
    ↓
SQLite（data/learner_model.db）
```

规则：

- **Router 不组织业务流程**，只取参并转交 Application Services。
- **UI 不直接操作 Learner Model**；一切画像变更经 `LearnerModelService`（统一事务 + change log + 幂等）。
- **SQLite 是唯一画像真值**；前端只有 UI 临时状态，不维护第二套画像。

## 数据流

### 学习计划

```
Course + Goal + Learner Context + Course Domain
        ↓
PlanContext（known / unknown / review / background / preferred_style）
        ↓
StudyPlanWorkflow（analyzer → decomposer → canonical KCGraph → plan builder → validator）
        ↓
study_plans + plan_steps + course_kc_graph（SQLite）
        ↓
PlanBriefService（确定性 PlanBrief） + ExplanationService（结构化讲解，lazy + cache）
        ↓
前端：PlanBrief → Learning Map（ELK DAG）→ Structured Explanation → Practice Handoff
```

### 对话

```
ChatService.chat(user_id, course_id?, message)
    ↓
记忆意图提取（extract_memory_intents：明确增删改画像的语义才处理）
    ↓
有课程 → ChatContext（课程名/目标/计划摘要/背景/偏好/记忆 + 可选 RAG）
无课程 → 普通对话
    ↓
LLM（或回退）→ chat_messages 落库
```

## 目录

```
src/edu_agent/
├── api/               FastAPI 路由（courses / plan / chat）
├── application/       CourseService / CourseCategoryService / StudyPlanService / ChatService / LearningContextService
├── learner_model/     SQLite Dynamic Learner Model（唯一画像真值）
├── adaptive/          plan_context.py / chat_context.py / course_resolver.py / service.py
├── domain/learning/   Course / KC / KCRelation / course_builder / kc_graph
├── workflows/study_plan/  唯一 workflow
├── core/              llm.py / agent_runner / exceptions
├── tools/             course_kb（RAG）/ kb_store / web_search / github_importer
└── config/            settings
```

## 相关文档

- [learner-model.md](./learner-model.md)
- [study-plan.md](./study-plan.md)
- [chat.md](./chat.md)
- [api.md](./api.md)
- [frontend.md](./frontend.md)
