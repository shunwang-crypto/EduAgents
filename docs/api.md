# API

FastAPI 入口：`src/edu_agent/api/main.py`。所有路由以 `/api` 为前缀。

`user_id` 通过 `X-User-Id` 请求头传入；缺省回退到配置 `LEARNER_MODEL_USER_ID`（开发默认）。Router 只取参转交 Application Services，不组织业务流程。

## Courses

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/courses` | 课程列表（含 goal / plan summary） |
| POST | `/api/courses` | 创建课程 `{topic, goal?, duration_days?, daily_minutes?}` |
| GET | `/api/courses/{course_id}` | 课程详情 |
| PATCH | `/api/courses/{course_id}` | 重命名 `{title}` |
| DELETE | `/api/courses/{course_id}` | 删除课程（domain + goals 取消 + plan 删除，events 保留审计） |

## Study Plan

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/courses/{course_id}/plan/generate` | 生成计划 `{goal?, duration_days?, daily_minutes?, background?, extra_requirement?}` |
| GET | `/api/courses/{course_id}/plan` | 获取计划（无计划 404）；返回含 `stages` 三阶段结构 |
| PATCH | `/api/courses/{course_id}/plan/steps/{step_id}` | 更新步骤状态 `{status: not_started\|in_progress\|completed}` |
| GET | `/api/courses/{course_id}/plan/steps/{step_id}` | 单个步骤详情（校验 user+course 归属） |

## Chat

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 发消息 `{message, course_id?, conversation_id?, plan_step_id?}` |
| GET | `/api/chat` | 取会话历史 `?course_id=&conversation_id=` |

Chat 返回：

```json
{
  "message_id": "...",
  "conversation_id": "...",
  "content": "...",
  "course_id": "... or null",
  "created_at": "...",
  "profile_updates": [],
  "context": {
    "type": "general | course | plan_step",
    "course_id": "...",
    "plan_step_id": "... or null",
    "step_title": "..."
  }
}
```

`plan_step_id` 可选：从计划「就此提问」进入时携带；后端校验 step 属于当前 user+course 的 current plan，不属于则忽略（降级为课程/普通上下文）。

## Health

`GET /api/health` → `{"status": "ok"}`

## 本地启动

```bash
pip install -r requirements.txt
uvicorn edu_agent.api.main:app --reload --port 8000
# 前端 dev：cd frontend && npm run dev（Vite 代理 /api → :8000）
```
