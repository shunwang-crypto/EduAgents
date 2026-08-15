# 普通 AI 对话

只有一个 `ChatService`（application/chat_service.py）。不存在 TopicTutor / KBQA / PlanChat 等独立聊天业务。

## 输入

```
ChatService.chat(user_id, message, course_id=None, conversation_id=None)
```

- **course_id=None**：普通对话，无课程上下文。
- **course_id 给定**：加载轻量课程上下文后回答。

## 有课程时

`ChatContext`（adaptive/chat_context.py）只选择：

- 课程名 / 学习目标
- 学习计划摘要（当前阶段、进度）
- 相关背景事实（Profile Facts）
- 相关长期偏好
- 相关 Semantic Memory（本课程 + 全局）
- 可选 RAG：问题与课程资料相关时检索（`tools/course_kb.py`），否则不检索

**不**把整份 Learner Model 塞给 LLM。

## 无课程时

普通对话正常工作，不强行映射 KC、不创建 Knowledge State、不调用课程策略；但仍会加载用户的**全局**画像、偏好和长期语义记忆，因此新建普通对话也能延续学习方式。

## 用户明确画像修改（记忆意图）

`extract_memory_intents` 负责明确删除等确定性操作；正常消息会同时交给 LLM 做受约束的结构化语义抽取。抽取只允许背景事实、稳定偏好和长期经历/目标，输出会经过字段白名单、长度和敏感信息校验，不允许模型删除画像或改写整份画像。

| 用户说 | 动作 |
|---|---|
| "我会 Python" / "我做过 FastAPI" | Profile Fact / Semantic Memory 创建或更新 |
| "其实我只是基础水平" | 同 key Fact UPDATE（confidence 重设） |
| "我更喜欢看代码示例，不太喜欢纯理论" | 语义提取为正/负向学习偏好 |
| "以后回答简洁一点" | `USER_EXPLICIT_PREFERENCE` |
| "这次只回答一句" | 仅本次请求，**不改**长期偏好 |
| "忘记我做过 FastAPI" | `PROFILE_FACT_DELETED` / `MEMORY_DELETED` 真正删除 |

规则：**LLM 永远不重写整份画像**；消息 → 意图 → 结构化 Mutation → Learner Model（统一事务）。

## 对话历史

- `chat_conversations`：每课程一个主 Conversation；无课程一个 General Conversation。
- `chat_messages`：role / content / created_at。
- 页面刷新后从 `GET /api/chat` 恢复当前对话。

## 事件

`CHAT_MESSAGE_SENT`（用户消息）、`CHAT_RESPONSE_DELIVERED`（AI 回复）写入 events；LLM 不可用时走确定性回退，对话流程不中断。
