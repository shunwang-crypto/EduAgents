import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../layout/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { StudyPlanPage } from "../features/study-plan/StudyPlanPage";

/** 最少路由：/ 与 /courses/:courseId/chat /courses/:courseId/plan */
export function AppRoutes() {
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
