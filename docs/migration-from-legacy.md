# 从旧架构迁移

本文记录：删除了什么、为什么删除、旧模块对应到新架构什么位置。

## 删除

| 旧模块 | 原因 | 对应新架构位置 |
| -- | -- | -- |
| `workflows/quiz/`（自适应练习：题库/生成一轮题/判题/更新 mastery） | 产品定位不再做练习业务 | 无（移除） |
| `workflows/quiz_generation/`、`workflows/mistake_reflection/`（占位 README） | 练习/错题业务废弃 | 无（移除） |
| `core/mastery.py`（本地 ±delta 变更：答对 +0.3 / 答错 -0.25） | 画像数值必须由合作伙伴更新，EduAgents 禁止本地变更 | `adaptive/policy.py` 只**读取** mastery 决策；`domain/kc_graph.py` 承接路径推荐 |
| `core/student_profile.py`（关键词推断 level → 第二套画像） | Source of Truth 冲突 | `integrations/learner_state/` 统一消费外部画像 |
| `tools/student_memory.py`（TODO 空壳） | 无实现 | `integrations/learner_state/semantic_memory` 概念 |
| `tests/test_quiz.py` / `test_mastery.py` / `test_student_profile.py` | 对应模块删除 | `test_architecture_contracts.py` 等替代 |
| `DecompositionResult.practice_directions` | 改名 | `application_directions` |
| `KnowledgeNode.practice_task` | 改名 | `application_task` |
| `TopicDetail.exercises` | 练习字段删除 | `next_learning_suggestions` |
| `DraftPlan` 中练习设计残留、`PracticePlan` 类 | 练习设计业务删除 | 无 |
| 前端"自适应练习"tab / 雷达图 / 学生水平下拉 | 本地 mastery/画像 UI 删除 | "学习画像"只读面板 |
| `student_profile` 相关 env/持久化 key | 第二套画像删除 | `LEARNER_STATE_*` |

## 改名与移动

| 旧 | 新 |
| -- | -- |
| `mastery.next_node` | `domain.kc_graph.recommended_next`（KST-lite 可达前沿） |
| kb_qa 的 `student_profile` prompt 变量 | `learner_context` + `adaptive_instructions` |
| study_plan/topic_tutor/plan_chat 的画像输入 | `learner_context` / `adaptive_instructions` |

## 保留（不动）

- `core/llm.py`（多模型 fallback）· `core/agent_runner.py` · `core/exceptions.py`
- `tools/course_kb.py`（RAG）· `kb_store.py` · `github_importer.py` · `web_search.py`
- `workflows/study_plan/`（清洗练习语后）· `kb_qa/` · `plan_chat/` · `topic_tutor/`
- 知识库问答的引用溯源 / 未覆盖拒答 / 澄清引导 / 降级

## 残留检查

```bash
# 确认无本地 mastery 变更 / 无练习系统 / 无第二套画像
grep -rn "mastery +=\|mastery -=\|update_mastery" src/        # 应为空
grep -rn "workflows.quiz\|PracticePlan\|student_profile" src/ # 应为空
```

`learning_report/` 占位目录保留（学情报告，非练习业务，未实现）。
