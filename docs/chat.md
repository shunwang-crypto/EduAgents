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

双路径，职责严格分离：

- **删除（「忘记/删掉/不再提」）**：永远走确定性规则（`extract_memory_intents`），先于一切抽取同步执行；LLM 没有删除权限。
- **新增/更新**：主路径是 LLM 受约束的结构化语义抽取；抽取 prompt 携带**已有画像**（active facts + 有效 memories，跨课程背景隔离），供模型去重——语义相同（只是措辞不同）的信息不重复入库。LLM 判定「本轮无值得保存」时**不会**退回正则，避免正则误报（如"我会尽快学完"→ `skill:尽快`）污染画像；只有 LLM 不可用/调用失败时才用确定性正则 fallback。
- **成本闸门**：无自述信号的消息（纯提问/指令）不调抽取 LLM。

抽取只允许背景事实、稳定偏好和长期经历/目标，输出经过字段白名单、长度和敏感信息校验（单轮最多 12 条），不允许模型删除画像或改写整份画像。

| 用户说 | 动作 |
|---|---|
| "我会 Python" / "我做过 FastAPI" | Profile Fact / Semantic Memory 创建或更新 |
| "其实我只是基础水平" | 同 key Fact UPDATE（confidence 重设） |
| "我更喜欢看代码示例，不太喜欢纯理论" | 语义提取为正/负向学习偏好 |
| "以后回答简洁一点" | `USER_EXPLICIT_PREFERENCE` |
| "这次只回答一句" | 仅本次请求，**不改**长期偏好 |
| "忘记我做过 FastAPI" | `PROFILE_FACT_DELETED` / `MEMORY_DELETED` 真正删除 |
| "忘记我学过 Rust，对了我是数学专业的" | 删除 Rust fact **且** 抽取教育背景（互不阻断） |
| "忘记我做过 XX"（无匹配记忆） | 响应 `profile_updates` 含 `delete:no-match:`，前端提示未命中 |

规则：**LLM 永远不重写整份画像**；消息 → 意图 → 结构化 Mutation → Learner Model（统一事务）。

### 延迟与降级

回复与画像抽取并行执行，但回复最多等待抽取 **15 秒**（`_MEMORY_WAIT_SECONDS`）；超时后抽取在后台线程自行落库（下一轮对话生效），HTTP 响应正常返回（只是 `profile_updates` 缺少该增量）。抽取 LLM 自身 timeout 20 秒。画像读取/抽取任何失败都不影响对话主流程。

## 对话历史

- `chat_conversations`：每课程一个主 Conversation；无课程一个 General Conversation。
- `chat_messages`：role / content / created_at。
- 页面刷新后从 `GET /api/chat` 恢复当前对话。

## 事件

`CHAT_MESSAGE_SENT`（用户消息）、`CHAT_RESPONSE_DELIVERED`（AI 回复）写入 events；LLM 不可用时走确定性回退，对话流程不中断。
