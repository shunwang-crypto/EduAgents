import { Routes } from "react-router-dom";
import { AppShell } from "../layout/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { StudyPlanPage } from "../features/study-plan/StudyPlanPage";
import { Navigate, Route } from "react-router-dom";

/** LearningApp：只负责 EduAgents 的 Routes（不创建 Router，宿主提供）。
 *
 * <LearningApp userId="..." /> 会注入 X-User-Id；宿主已有 Router 时直接挂载，
 * standalone 由 main.tsx 包 BrowserRouter。
 */
export function LearningApp(_props: { userId: string; basePath?: string }) {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/courses/:courseId/chat" element={<ChatPage />} />
        <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
