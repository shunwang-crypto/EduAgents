/** API Client：Fetch 封装。user_id 走 X-User-Id 头（宿主接认证时替换）。 */
import type {
  ChatResponse,
  Conversation,
  Course,
  PlanStep,
  StudyPlan,
} from "./types";

// 开发期默认用户（宿主接入后由宿主注入 userId）
export const DEV_USER_ID = import.meta.env.VITE_DEV_USER_ID ?? "STU-001";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": DEV_USER_ID,
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  // Courses
  listCourses: () => request<Course[]>("/api/courses"),
  createCourse: (body: { topic: string; goal?: string; duration_days?: number; daily_minutes?: number }) =>
    request<Course>("/api/courses", { method: "POST", body: JSON.stringify(body) }),
  getCourse: (courseId: string) => request<Course>(`/api/courses/${courseId}`),
  renameCourse: (courseId: string, title: string) =>
    request<Course>(`/api/courses/${courseId}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteCourse: (courseId: string) =>
    request<void>(`/api/courses/${courseId}`, { method: "DELETE" }),

  // Study Plan
  generatePlan: (courseId: string, body: { goal?: string; duration_days?: number; daily_minutes?: number; background?: string }) =>
    request<StudyPlan>(`/api/courses/${courseId}/plan/generate`, { method: "POST", body: JSON.stringify(body) }),
  getPlan: (courseId: string) => request<StudyPlan>(`/api/courses/${courseId}/plan`),
  updateStep: (courseId: string, stepId: string, status: string) =>
    request<StudyPlan>(`/api/courses/${courseId}/plan/steps/${stepId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  getStep: (courseId: string, stepId: string) =>
    request<PlanStep>(`/api/courses/${courseId}/plan/steps/${stepId}`),

  // Chat
  chat: (body: {
    message: string;
    course_id?: string | null;
    conversation_id?: string | null;
    plan_step_id?: string | null;
  }) => request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify(body) }),
  getChat: (courseId?: string | null, conversationId?: string | null) =>
    request<Conversation>(
      `/api/chat?course_id=${courseId ?? ""}&conversation_id=${conversationId ?? ""}`
    ),
};
