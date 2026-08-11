import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../layout/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { StudyPlanPage } from "../features/study-plan/StudyPlanPage";
import { ApiProvider } from "../api/ApiProvider";

export interface LearningAppProps {
  userId: string;
  basePath?: string;
}

/** LearningApp：Providers + Routes。
 * - 不创建 BrowserRouter（宿主已有 Router 时直接挂载；standalone 由 main.tsx 包）；
 * - userId 经 ApiProvider 注入 X-User-Id 头。
 */
export function LearningApp({ userId }: LearningAppProps) {
  return (
    <ApiProvider userId={userId}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/courses/:courseId/chat" element={<ChatPage />} />
          <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ApiProvider>
  );
}
