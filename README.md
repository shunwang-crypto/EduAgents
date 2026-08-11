# EduAgents

**课程 + 个性化学习计划 + 普通 AI 对话** —— 后台带轻量动态学习者模型的智能学习助手。

## 产品范围

三个用户可见核心能力：

1. **我的课程** — 创建 / 查看 / 切换 / 重命名 / 删除课程
2. **学习计划** — 每门课程一个个性化计划（固定三阶段：基础准备 / 核心学习 / 综合应用）；每步可「就此提问」进入知识点上下文对话；GPT 风格 Rich Markdown（表格 / 代码 / LaTeX 数学）
3. **普通 AI 对话** — 无课程普通对话 / 带课程上下文 / 带计划步骤上下文（PlanStepContext）

后台保留轻量 **Dynamic Learner Model**（SQLite 唯一画像真值），让计划更贴合背景、对话更个性化。
**不做**：今日学习、学习画像页面、学习路径、Topic Tutor、知识库问答独立业务、Quiz / Practice / Mistake、排行榜等。

## 技术栈

FastAPI · React + TypeScript + Vite · SQLite（WAL）· LLM（可选，含回退）· RAG（可选）

## 架构

```
Frontend (React, frontend/)
    ↓ HTTP
FastAPI (src/edu_agent/api)
    ↓
Application Services (src/edu_agent/application)
    ├─ CourseService      课程 CRUD / 自然语言解析
    ├─ StudyPlanService   生成/读取/更新学习计划
    ├─ ChatService        普通对话 + 记忆意图提取 + ChatContext
    └─ LearningContextService
    ↓
learner_model/（SQLite） · adaptive/（plan_context / chat_context / course_resolver）
workflows/study_plan/（唯一 workflow） · core/llm · tools/course_kb（RAG）
    ↓
SQLite（data/learner_model.db）
```

关键规则：

- **SQLite 是唯一画像真值**，前端不维护第二套画像；Router 不组织业务流程。
- **UNKNOWN ≠ 0**：无证据的 mastery 是 NULL，绝不当作 0；弱证据绝不自动抬高 mastery。
- **统一事务**：一切画像变更经 `LearnerModelService`（BEGIN → mutation → change log → event → COMMIT，异常 ROLLBACK；INSERT OR IGNORE 保证事件幂等）。
- **多课程隔离**：任意主题建立独立 course_id（`CUSTOM-{slug}-{hash8}`），Java 状态不污染 Python。
- **用户显式声明 > 推断**：聊天中"我会 Python"→ Profile Fact；"以后简洁一点"→ 偏好；"忘记我做过 FastAPI"→ 真正删除。

## 快速开始（WSL · conda 环境 `EduAgent`）

```bash
# ---------- 后端（WSL 终端）----------
cd ~/EduAgents
conda activate EduAgent                 # conda 环境名 EduAgent（/home/shunw/miniforge3/envs/EduAgent）
pip install -r requirements.txt         # 首次或依赖变更后执行；已装可跳过
cp -n .env.example .env                 # 首次配置；已有 .env 时跳过（-n 不覆盖，避免丢旧配置）
PYTHONPATH=src uvicorn edu_agent.api.main:app --reload --port 8000

# ---------- 前端（另开一个 WSL 终端）----------
cd ~/EduAgents/frontend
npm install                             # 首次或依赖变更后执行；已装可跳过
npm run dev                             # http://localhost:5173，Vite 代理 /api → :8000
```

说明：

- **src-layout**：代码在 `src/edu_agent/`（无 pyproject/setup.py），启动必须带 `PYTHONPATH=src`，否则 `ModuleNotFoundError: edu_agent`。
- **LLM 可选**：无 key 走确定性回退，可直接体验；有 key 填 `.env` 的 `OPENAI_API_KEY` / `OPENAI_BASE_URL`（默认 DeepSeek）。
- **用户标识**：`LEARNER_MODEL_USER_ID` 留空时，请求必须带 `X-User-Id` 头（宿主嵌入场景）；本地开发可设为 `STU-001` 省去每次传头。
- 数据库自动创建于 `data/learner_model.db`（WAL）；改了 schema 约束后需删除旧库再启动。

打开 http://localhost:5173 → 普通对话直接聊天；点侧边栏「+」按课程主题创建课程；进入课程后点「学习计划」生成三阶段计划。

## 目录

```
src/edu_agent/
├── api/                FastAPI 路由（courses / plan / chat）
├── application/        CourseService / StudyPlanService / ChatService / LearningContextService
├── learner_model/      SQLite Dynamic Learner Model（db / repository / service / updaters）
├── adaptive/           plan_context / chat_context / course_resolver / service
├── domain/learning/    Course / KC / KCRelation / course_builder / kc_graph
├── workflows/study_plan/  唯一 workflow
├── core/               llm / agent_runner / exceptions
├── tools/              course_kb（RAG）/ kb_store / web_search / github_importer
└── config/             settings
frontend/               React + TypeScript + Vite 前端
docs/                   架构 / 画像 / 计划 / 对话 / API / 前端
data/                   SQLite（learner_model.db，gitignore）
```

## 文档

- [docs/architecture.md](docs/architecture.md) — 架构总览
- [docs/learner-model.md](docs/learner-model.md) — 动态学习者模型
- [docs/study-plan.md](docs/study-plan.md) — 学习计划
- [docs/chat.md](docs/chat.md) — 普通对话与记忆意图
- [docs/api.md](docs/api.md) — API
- [docs/frontend.md](docs/frontend.md) — 前端

## 测试

```bash
pytest tests/ -v
```

覆盖：CourseService CRUD / StudyPlanService 生成与进度 / ChatService 记忆意图（新增/修改/删除 Fact、偏好、多课程隔离）/ CourseResolver / Chat 历史 / API / 迁移-less fresh DB / 既有 workflow 回归。
