# 学习计划

每门课程**一个**学习计划。入口唯一：`StudyPlanService`（application/study_plan_service.py）→ `workflows/study_plan/`（唯一 workflow）。不存在第二套计划表单或重复 workflow。

## 输入

用户不需要填十几个参数。支持两种方式：

1. 表单 / API 直接给：`goal, duration_days, daily_minutes, optional_background, optional_extra_requirement`
2. 自然语言：`parse_course_intent`（course_service.py）解析"我想两周学习 Python 数据分析，每天一小时"这类句子

## 自适应（在生成计划**前**）

`PlanContext`（adaptive/plan_context.py）在分解知识路径**之前**从 Learner Model 构造：

```json
{
  "goal": "...",
  "known_topics": ["..."],
  "unknown_topics": ["..."],
  "topics_needing_review": ["..."],
  "background": ["..."],
  "preferred_style": ["..."],
  "daily_minutes": 60,
  "duration_days": 14
}
```

决定"学什么 / 先学什么 / 跳过什么 / 复习什么"时已经参考用户状态：

- `mastery ≥ 0.7` 且置信 → known（可跳过）
- `mastery 为 NULL` → unknown（中性对待，不武断"不会"）
- `mastery 低 + 置信高` → needs review
- 无画像 → 不编造，计划按通用顺序

生成的计划附带一句人话说明，如"已根据你的 Python 基础跳过语法入门"，**不暴露** mastery / reason code / policy JSON。

## 计划结构（固定三阶段）

- `study_plans`：goal / duration_days / daily_minutes / progress / plan_markdown / personalization_note
- `plan_steps`：step_id（`PLANSTEP-{uuid}`）/ seq / **stage_id / stage_title / stage_order** / **kc_id**（= KnowledgeNode.id）/ 标题 / 说明 / **learning_objective / prerequisites / difficulty** / 预计时间 / 状态
- **一级结构固定 3 个阶段**：基础准备（order=1）/ 核心学习（order=2）/ 综合应用（order=3），标题可按主题自定义（如 Transformer：数学与注意力基础 / 核心机制 / 应用与整合）；每个阶段至少 1 个步骤，不允许空阶段。
- **时间预算是硬约束**：UI 步骤的预计分钟总和不得超过 `学习周期 × 每日时长`。当 LLM 拆出的知识点过多时，确定性裁剪步骤并按原难度权重缩放分钟数；三个阶段仍各保留至少 1 步。
- `get_plan` DTO 返回 `stages: [{stage_id, stage_title, order, steps[]}]`，前端按阶段渲染，不从字符串猜阶段。

## 就此提问（Plan Step Context）

每个计划步骤支持「就此提问」→ 进入 `GET /courses/{course_id}/chat?step={step_id}`：
- Chat 请求携带 `plan_step_id`，后端校验 step 属于当前 user+course 的 current plan（跨课程/跨用户拒绝，仅提示不报错）；
- 注入 PlanStepContext（阶段/知识点/学习目标/前置/难度）+ RAG（query=step.title+message，top_k=3）；
- step 上下文只作用于单次请求，可随时移除（Chip ×），不永久绑定会话。

步骤状态只三态：`not_started / in_progress / completed`。每个 Step 只有状态 + 就此提问，没有练习按钮。

## 重新生成

每课程一个 current plan：`generate_plan` 在事务内删除旧 plan+steps 再建新 plan（失败旧 plan 仍可用），不无限累积不可访问的计划。

## 进度

- **唯一正式来源**：`plan_steps` 计算 → 同步 `study_plans.progress` → 同步 `learner_course_states.progress` / `learning_goals.progress`。
- 步骤标记 `completed` **只更新进度**，**绝不修改任何 KC 的 mastery**（`PLAN_STEP_COMPLETED` 事件仅记行为）。
- 点击步骤状态变化触发 `PLAN_STEP_STARTED / PLAN_STEP_COMPLETED` 事件。

## 生成流程

```
StudyPlanService.generate_plan(user_id, course_id, goal, ...)
    ├─ 校验课程存在 / 取课程 goal
    ├─ 写 optional_background → USER_EXPLICIT_PROFILE_FACT（若填）
    ├─ build_plan_context（画像 → PlanContext）
    ├─ run_study_plan_workflow（analyzer → decomposer → canonical KCGraph → plan builder → validator）
    ├─ 保存 study_plans + plan_steps（事务）
    ├─ 持久化 / 更新 dynamic KCGraph（course_kc_graph）
    ├─ 持久化 PlanBrief（plan_brief_json；缺失时 get_plan 懒 backfill）
    ├─ 失效旧 Structured Explanation 缓存（step_explanations）
    ├─ 更新 course progress / goal
    └─ PLAN_CREATED 事件
```

## PlanBrief（为什么这样安排）

`PlanBriefService` 从 StudyPlan + KCGraph + LearnerModel 确定性构建，不额外调用 LLM：
- goal / target_outcome
- `known_skills`（mastery ≥ 0.7）、`skill_gaps`（mastery < 0.7）、`unassessed_skills`（mastery=None；**UNKNOWN 绝不进能力缺口**）
- `critical_path`：真实 DAG 最长路径（DP on topological order），DTO 为 `PathItem{kc_id, name}`，前端只显示 name
- `adaptation_rules` / `difficulty_hotspots` / `stage_overview`

## Learning Map 推荐语义

`LearningMapService`（application/learning_map_service.py）：
- **goal KC**：优先显式 target；缺省取**末端叶子 KC**（无后继），**不等于全部组件**
- **current_recommended_kc**：最多一个（现在最建议学）
- **recommended_candidates**：其它 1~3 个可学候选（不显示推荐 badge）
- **active_path**：真实 DAG 路径（相邻节点必有 prerequisite edge）
- 兼容旧 `recommended_path` 字段（新前端不再当真实路径使用）
- 旧课程（Plan 存在、graph 缺失）：`CourseGraphService.try_recover_from_plan` 从 plan_steps 自动恢复并 migrate

## Structured Explanation（结构化讲解）

`ExplanationService`（application/explanation/）替换旧 lesson_markdown 长文：
- `ExplanationContextBuilder`：learner profile + course goal + KC（titles）+ plan context + RAG sources
- `ExplanationGenerator`：LLM schema 输出结构化 blocks（orientation/big_picture/concept/worked_example/code_walkthrough/contrast/misconception/application/recap/handoff）；离线用确定性 fallback（只使用知识点名称，不含 kc_id）
- `ExplanationValidator`：block type 合法 / 非空 / 无 exercise / 无重复
- 缓存：`step_explanations` 表，按 `context_hash` 复用；`invalidate_explanation` 在重建计划 / 删课程时清理
- **不生成练习 / 判题**（见 test_no_exercise）

## Practice Handoff

只定义接口契约（`PracticeHandoff` DTO：course_id/plan_id/step_id/kc_id/objective/difficulty/source=study_plan/return_url），本模块**不实现练习**。

## 用户界面去工程化

内部 KC / kc_id / ReasonCode / Evidence / LearnerModel 是内部概念；用户界面统一显示：
- 知识点 / 掌握度 / 评估可信度 / 学习状态 / 推荐原因 / 学习记录 / 学习讲解 / 当前推荐 / 前置知识未满足
- 内部 ID 只作为 React key / API 参数，绝不作为 visible text

## API

见 [api.md](./api.md)：`POST /api/courses/{id}/plan/generate`、`GET .../plan`、`PATCH .../plan/steps/{step_id}`、`GET .../plan/steps/{step_id}`、`GET /api/courses/{id}/plan-brief`、`GET /api/courses/{id}/plans/{plan_id}/steps/{step_id}/explanation`、`POST /api/courses/{id}/plans/{plan_id}/steps/{step_id}/handoff`。
