# 前端（React + TypeScript + Vite）

ChatGPT 式信息架构：**左侧 Sidebar + 单一 Main Content**，无永久右侧第三栏。

## 目录

```
frontend/
├── src/
│   ├── app/          App.tsx / router.tsx
│   ├── layout/       AppShell.tsx / Sidebar.tsx / MainLayout.tsx
│   ├── features/     courses/（CreateCourseModal）chat/（ChatPage、Composer、EmptyState）
│   │                 study-plan/（StudyPlanPage、LearningMapView、learn/LearnPage、explanation/ExplanationDocument）
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
| `/courses/:courseId/plan` | 课程学习计划（学习地图 + 计划列表） |
| `/courses/:courseId/learn/:stepId` | 独立讲解页（Rich Learning Document） |

无 profile / today / path / qa / tutor / dashboard 路由。路径一律用 `app/navigation.ts` 的 helper（`coursePlanPath` / `courseLearnPath` / `courseChatPath`）生成，保持宿主前缀。

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

只回答「我应该怎么学、现在在哪、为什么推荐 / 学习顺序与进度」，**不内嵌讲解正文**：

- 学习地图：PlanBrief + 知识点状态 + 推荐原因 + 每个节点的 `开始讲解` 入口。默认只取景「当前知识点 + 前后 2~3 个相关节点」，不把整条长路线 fit 成一条细线；`完整知识图` 模式才 fit 全图，`回到当前` 一键复位。
- 计划列表：文档式布局（非 Dashboard），阶段分组 → 步骤列表（序号 / 标题 / 说明 / 预计时间 / ○未开始 ◐进行中 ✓已完成）+ `开始讲解` / `就此提问`。顶部可显示一句个性化说明。
- 不显示 mastery / confidence / reason code；步骤不展开 Markdown。

## 独立讲解页

`/courses/:courseId/learn/:stepId`（`study-plan/learn/LearnPage`）：真正学习知识内容的地方，地图节点与计划列表进入的是**同一个**页面。

- 长文档 + 目录导航 + 自然滚动：左侧目录（移动端顶部横向目录）点击滚动到对应小节，`IntersectionObserver` 高亮当前节；**没有**「第 N/M 部分 → 下一部分」卡片翻页。
- 篇幅随知识点复杂度变化，结构不固定；支持 Markdown 标题/列表/代码/表格/LaTeX、结构化 `diagram`（按依赖分层渲染成流程图）与真实图片 `image`。
- 顶部常驻 `返回学习地图`；进入即把 `not_started` 的步骤置为 `in_progress`。
- 底部两个**独立**动作：`完成本节讲解`（只更新 PlanStep 进度，**不修改 mastery**）与 `进入相关实践`。

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
