# 前端（React + TypeScript + Vite）

ChatGPT 式信息架构：**左侧 Sidebar + 单一 Main Content**，无永久右侧第三栏。

## 目录

```
frontend/
├── src/
│   ├── app/          App.tsx / router.tsx
│   ├── layout/       AppShell.tsx / Sidebar.tsx / MainLayout.tsx
│   ├── features/     courses/（CreateCourseModal）chat/（ChatPage、Composer、EmptyState）study-plan/（StudyPlanPage）
│   ├── api/          client.ts / types.ts
│   ├── styles/       tokens.css / globals.css
│   └── main.tsx
├── package.json / vite.config.ts / tsconfig.json / index.html
```

## 路由（最小集）

| 路径 | 内容 |
|---|---|
| `/` | 无课程状态：Empty State + 自然语言创建课程 |
| `/courses/:courseId/chat` | 课程对话 |
| `/courses/:courseId/plan` | 课程学习计划 |

无 profile / today / path / qa / tutor / dashboard 路由。

## Sidebar

- 顶部：EduAgents + 新对话
- 我的课程（列表）+ 新建课程
- 不显示：今日学习 / 最近学习 / 学习画像 / 学习路径 / 知识库 / 错题 / 练习 / 设置 / 服务状态
- 课程项只显示课程名，无进度条 / mastery / 薄弱项
- 桌面 240px，可折叠到 56px；移动端 Drawer

## Chat 页

- Main 居中，内容最大宽 860px；大量留白，AI 消息左侧正文、用户消息简洁气泡
- Composer 固定底部居中：圆角大输入框，Enter 发送、Shift+Enter 换行、发送按钮、Loading 态
- Placeholder：无课程"有什么我可以帮你的？"；有课程"继续问关于 Python 数据分析的问题……"
- 无课程 Empty State："今天想学习什么？" + 最多 3 个建议

## 学习计划页

文档式布局（非 Dashboard）：目标 + 周期行 → 阶段分组 → 步骤列表（序号 / 标题 / 说明 / 预计时间 / ○未开始 ◐进行中 ✓已完成）。顶部可显示一句个性化说明。不显示 mastery / confidence / reason code。

## 视觉

浅灰背景 + 白色主内容 + 高留白 + 绿色 Primary（`--primary: #176B55`）。设计令牌集中在 `styles/tokens.css`（`--bg-app / --bg-sidebar / --text-primary / --border / --radius-* / --sidebar-width / --content-max-width / --composer-width`）。

## 作为宿主模块

不实现登录 / 账户中心 / 全局导航 / 设置。Main Root 支持 `height: 100%`，可被宿主以 `<LearningApp userId={...}/>` 方式挂载。

## 开发

```bash
cd frontend
npm install
npm run dev      # Vite 代理 /api → http://localhost:8000
npm run build    # 产物 frontend/dist
npm test
```
