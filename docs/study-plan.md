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

## 计划结构

- `study_plans`：goal / duration_days / daily_minutes / progress / plan_markdown / personalization_note
- `plan_steps`：step_id / 序号 / 标题 / 说明 / 预计时间(分钟) / 状态

步骤状态只三态：`not_started / in_progress / completed`。

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
    ├─ run_study_plan_workflow（analyzer → decomposer → planner → validator → reviewer）
    ├─ 保存 study_plans + plan_steps（事务）
    ├─ 更新 course progress / goal
    └─ PLAN_CREATED 事件
```

## API

见 [api.md](./api.md)：`POST /api/courses/{id}/plan/generate`、`GET .../plan`、`PATCH .../plan/steps/{step_id}`。
