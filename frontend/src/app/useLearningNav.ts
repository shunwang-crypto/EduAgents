/** 统一导航 hook：基于当前 pathname 推导 LearningApp 根，提供 host-relative 跳转。
 * 所有页面（AppShell / Sidebar / CourseHeader / StudyPlanPage）共用，禁止各自拼绝对路径。 */
import { useLocation, useNavigate } from "react-router-dom";
import { courseChatPath, courseLearnPath, coursePlanPath, generalChatPath } from "./navigation";

export function useLearningNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return {
    /** 进入 General Chat（普通对话）。可选携带 conversation_id；replace=true 用于「新对话」原地替换。 */
    openGeneralChat: (conversationId?: string | null, replace = false) =>
      navigate(generalChatPath(pathname, conversationId), replace ? { replace: true } : undefined),
    /** 进入某课程的 Chat；可选携带 conversation_id 或 plan step。 */
    openCourseChat: (
      courseId: string,
      opts?: { conversationId?: string | null; stepId?: string | null }
    ) => navigate(courseChatPath(pathname, courseId, opts)),
    /** 进入某课程的 Plan。 */
    openCoursePlan: (courseId: string) => navigate(coursePlanPath(pathname, courseId)),
    /** 进入独立讲解页（地图页与计划列表共用同一入口）。 */
    openCourseLearn: (courseId: string, stepId: string) =>
      navigate(courseLearnPath(pathname, courseId, stepId)),
  };
}
