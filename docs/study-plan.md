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

- `study_plans`：goal / duration_days / daily_minutes / progress / plan_markdown（仅 legacy/export，**不参与** Learning Map / Recommendation / PlanBrief / Explanation / Plan List）/ personalization_note
- `plan_steps`：step_id（`PLANSTEP-{uuid}`）/ seq / **stage_id / stage_title / stage_order** / **kc_id**（= KnowledgeNode.id = canonical KC id）/ 标题 / 说明 / **learning_objective / prerequisites / difficulty** / 预计时间 / 状态
- **一级结构固定 3 个阶段**：基础准备（order=1）/ 核心学习（order=2）/ 综合应用（order=3），标题可按主题自定义；每个阶段至少 1 个步骤，不允许空阶段。
- **时间预算是硬约束**：UI 步骤的预计分钟总和不得超过 `学习周期 × 每日时长`。当 LLM 拆出的知识点过多时，确定性裁剪步骤并按原难度权重缩放分钟数；三个阶段仍各保留至少 1 步。
- `get_plan` DTO 返回 `stages: [{stage_id, stage_title, order, steps[]}]`，前端按阶段渲染，不从字符串猜阶段。

## 结构化拆解（ConceptSpec / prerequisite DAG）

Decomposer 输出 `DecompositionResult.concepts: List[ConceptSpec]`（不再是散乱字符串数组）：

- 每个 `ConceptSpec` 提供：`temp_id / title / summary / learning_objective / category(prerequisite|core|target|application) / content_type(theory|code|mixed) / difficulty / stage_order / prerequisite_refs / is_target / estimated_minutes`
- **graph edge 只来自 `prerequisite_refs`（显式声明）**；Stage 只用于 Plan List 分组 / 调度 / 展示，**绝不自动创造依赖**（禁止"所有前置 → 所有核心"的稠密错误图）。
- canonicalization：`ConceptSpec.temp_id → canonical kc_id`，保证 StudyPlan step / KCGraph / LearningMap / LearnerModel 使用同一 canonical id。
- `target_refs` / `is_target` 显式给出真正目标 KC（缺省回退到 graph 末端叶子节点）。
- Graph validator 校验 duplicate / dangling / self loop / cycle / duplicate edge / empty / missing target；失败走有限 repair + deterministic fallback。
- 旧字段 `core_concepts / prerequisite_concepts / learning_sequence` 仅 compatibility，不再作为 Graph source of truth。
- **Compatibility fallback**（当 `concepts` 为空，如 OFFLINE/legacy）只从旧字段恢复节点与展示顺序；
  `learning_sequence` / Stage / PlanStep.seq 都不能被解释为 prerequisite，不会为了连通性自动补边。
- target fallback：优先 `target_refs` / `is_target`，缺省 sequence 末节点 / terminal node。

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
- `difficulty_hotspots`：优先来自 `DecompositionResult.difficulty_points`（plan generation 时持久化）；缺省回退 difficulty 标记的进阶/困难步骤
- `adaptation_rules` / `stage_overview`
- 缺失（legacy plan）时 `get_plan` 懒 backfill 并持久化（确定性构建）

## Learning Map 推荐语义

`LearningMapService`（application/learning_map_service.py）：
- **target_kcs**：真正目标 KC（优先显式 target；缺省取**末端叶子 KC**，无后继，**不等于全部组件**）
- **current_recommended_kc**：最多一个（现在最建议学）
- **recommended_candidates**：其它 1~3 个可学候选（不显示推荐 badge）
- **active_subgraph_nodes / active_subgraph_edges**：goal prerequisite closure（targets + 传递前置）；含未来 locked 节点与支撑前置，作为"当前学习路线"模式的数据
- **primary_route**：从当前推荐到某主目标的一条**真实 DAG 路径**（相邻节点必有 prerequisite edge）；未来 locked 节点允许存在
- **active_path**：兼容旧字段（真实 DAG 路径）；`recommended_path` 仅 legacy
- **推荐 tie-break**：优先 StudyPlan.seq，其次拓扑深度，最后 kc_id（绝不由 hash 类 canonical id 决定顺序）
- **PREREQUISITE_FOR_GOAL** 方向：某 KC 是 target 的传递前置（kc ∈ transitive_prerequisites(target)），target 自身不算
- 旧课程（Plan 存在、graph 缺失）：`CourseGraphService.try_recover_from_plan` 从 plan_steps 自动恢复并 migrate；不可恢复时 UI 显示"升级学习地图"，不显示"生成学习计划"

## 页面职责划分（产品形态）

三个界面各管一件事，互不混装：

| 界面 | 路由 | 只负责 |
| --- | --- | --- |
| 学习地图 | `/courses/:courseId/plan`（地图标签） | 我应该怎么学、现在在哪、为什么推荐：PlanBrief、地图、知识点状态、推荐原因、`开始讲解` 入口 |
| 计划列表 | `/courses/:courseId/plan`（计划列表标签） | 学习顺序、时间、进度 |
| 独立讲解页 | `/courses/:courseId/learn/:stepId` | 真正学习知识内容（Rich Learning Document） |

- 讲解**不再**挂在地图或计划列表下方；地图节点 CTA 与计划列表按钮进入**同一个** `learn` 页。
- `learn` 页顶部常驻 `返回学习地图`；进入即把 `not_started` 的 PlanStep 置为 `in_progress`（直接访问 URL / 刷新同样生效，由 `LearnPage` 单点负责）。
- 地图默认只取景「当前知识点 + 前后 2~3 个相关节点」，不把整条长路线 fitView 成一条细线；`完整知识图` 模式才 fit 全图，另有 `回到当前` 一键复位。

## Adaptive Rich Explanation（自适应丰富讲解）

`ExplanationService`（application/explanation/）生成可自然滚动阅读的富讲解文档：
- `ExplanationContextBuilder`：KC 描述 + PlanStep 学习目标 + learner profile + RAG sources（不把 prerequisite graph 注入正文提示）
- `ExplanationGenerator`：LLM 根据知识点标题/描述、学习目标、学习者背景、内容类别与可用资料动态选择教学能力；**不设固定字数、固定 section 数量或固定模板**。候选池只是可选能力，不强制代码、公式、表格、图片或图示。复杂知识点写几千字是正常的，禁止把每节写成一两句提纲。正文从当前知识开始，不生成学习路线规划说明。
- `ExplanationValidator`：block type 合法 / 非空 / 无 exercise / 无重复，不按篇幅和 section 数量裁剪
- 图示：优先结构化 `diagram`（`data.nodes` + `data.edges`，前端按依赖分层渲染成流程图，分支同层并排）；`image` 只在存在真实图片资料时使用，**不强制每个知识点都出图**
- 前端：长文档 + 左侧目录（移动端顶部横向目录）+ 自然滚动，**没有**「第 N/M 部分 → 下一部分」卡片翻页；Markdown 支持标题、列表、代码、表格、图片与 LaTeX
- 离线降级（`EDU_OFFLINE=1` 或 LLM 失败）：只展示 context 中真实存在的 KC 描述与学习目标；没有足够依据时明确提示无法生成，不用通用学习方法冒充讲解，也不编造代码、公式、图或关系表
- 缓存：`step_explanations` 表按带生成器版本的 `context_hash` 复用；教学契约变更会自动淘汰旧规划式内容
- **不生成练习 / 判题**（见 test_no_exercise）
- 文档末尾提供两个**不同**动作：`完成本节讲解`（把 PlanStep.status → completed，只更新进度，**绝不修改 mastery**）与 `进入相关实践`（Practice Handoff）

## Practice Handoff

只定义接口契约（`PracticeHandoff` DTO：course_id/plan_id/step_id/kc_id/objective/difficulty/source=study_plan/return_url），本模块**不实现练习**。外部模块未接通时 UI 显示"相关实践功能暂未开放"。

## 用户界面去工程化

内部 KC / kc_id / ReasonCode / Evidence / LearnerModel 是内部概念；用户界面统一显示：
- 知识点 / 掌握度 / 评估可信度 / 学习状态 / 推荐原因 / 学习记录 / 学习讲解 / 当前推荐 / 前置知识未满足
- 内部 ID 只作为 React key / API 参数，绝不作为 visible text

## API

见 [api.md](./api.md)：`POST /api/courses/{id}/plan/generate`、`GET .../plan`、`PATCH .../plan/steps/{step_id}`、`GET .../plan/steps/{step_id}`、`GET /api/courses/{id}/plan-brief`、`GET /api/courses/{id}/plans/{plan_id}/steps/{step_id}/explanation`、`POST /api/courses/{id}/plans/{plan_id}/steps/{step_id}/handoff`。
