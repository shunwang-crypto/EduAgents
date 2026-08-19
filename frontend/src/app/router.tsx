import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../layout/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { StudyPlanPage } from "../features/study-plan/StudyPlanPage";
import { LearnPage } from "../features/study-plan/learn/LearnPage";
import { ApiProvider } from "../api/ApiProvider";

export interface LearningAppProps {
  userId: string;
}

/** LearningApp：Providers + Routes。
 * - 不创建 BrowserRouter（宿主已有 Router 时直接挂载；standalone 由 main.tsx 包）；
 * - userId 经 ApiProvider 注入 X-User-Id 头；
 * - 路由使用相对路径，宿主可挂载到任意前缀，例如：
 *   <Route path="/adaptive-learning/*" element={<LearningApp userId={user.id} />} />
 */
export function LearningApp({ userId }: LearningAppProps) {
  return (
    <ApiProvider userId={userId}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="" element={<ChatPage />} />
          <Route path="courses/:courseId/chat" element={<ChatPage />} />
          <Route path="courses/:courseId/plan" element={<StudyPlanPage />} />
          {/* 独立讲解页：学习地图与计划列表都进入这里；讲解内容不再挂在地图下方 */}
          <Route path="courses/:courseId/learn/:stepId" element={<LearnPage />} />
          <Route path="*" element={<Navigate to="" replace />} />
        </Route>
      </Routes>
    </ApiProvider>
  );
}
