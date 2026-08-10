# 多课程模型（Multi-Course）

## 核心原则

所有课程状态以 `(user_id, course_id)` 隔离；全局状态（身份/事实/跨课程偏好/全局记忆）以
`(user_id)` 隔离并带 `global_state_version`。业务层禁止到处使用默认 `course_id`。

## LearningContext（统一上下文）

`learner_model/schemas.py::LearningContext`：`user_id / course_id / goal_id / session_id`。

所有 AdaptiveService / LearningEvent / Workflow 调用必须携带当前 LearningContext；
前端通过 `_current_learning_context()`（`_current_course_id` 来自学习计划提交时的 CourseResolver）取得。

## CourseResolver（`adaptive/course_resolver.py`）

`resolve_course_id(topic)`：
1. 内置课程关键词（Java OOP → `JAVA-OOP`、Transformer → `TRANSFORMER`）命中 → 内置 ID；
2. 已有自定义课程 slug 匹配 → 复用；
3. 否则 `CUSTOM-{slug-or-hash}`（稳定，不随机变化）。

`resolve_goal_id(user_id, course_id)`：稳定且 user scoped（`GOAL-{user}-{course}`）。

## 自定义课程 Domain Model 持久化

学习计划生成后：
1. `build_course_from_nodes(KnowledgeMap nodes)` → `Course`（`KnowledgeNode.id` 即 course-local kc_id；
   前置字符串映射为同课程 kc_id）；
2. `register_course`（内存）+ `persist_course`（SQLite `domain_courses/domain_kcs/domain_kc_relations`）；
3. 重启后 `load_course_from_repo` 恢复（`adaptive/service.py::resolve_course_for`：先内置注册表，再 SQLite）。

## 隔离验证

- Java 的 KC/误解/课程记忆不会出现在 Transformer bundle（`(user_id, course_id)` 全键）。
- 全局记忆（`course_id=''`）两类课程都能看到；课程记忆只有本课程能看到。
- 全局偏好（`course_id=''`）共享；课程偏好（`course_id=xxx`）只影响本课程。
- `goal` 以 `(user_id, goal_id)` 联合主键，两个用户可用相同 goal_id 互不覆盖。
