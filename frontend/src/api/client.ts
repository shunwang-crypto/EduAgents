/** API Client：Fetch 封装。user_id 由 LearningApp 注入（setApiUserId），
 * 业务代码不写死任何用户。 */
import type {
  ChatResponse,
  Conversation,
  Course,
  PlanStep,
  StudyPlan,
} from "./types";

let currentUserId = "";

/** 由宿主 LearningApp 注入当前用户（X-User-Id 头）。 */
export function setApiUserId(userId: string) {
  currentUserId = userId || "";
}

export function getApiUserId(): string {
  return currentUserId;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": currentUserId,
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
  createConversation: (courseId?: string | null) =>
    request<{ conversation_id: string; course_id: string | null }>("/api/chat/conversations", {
      method: "POST",
      body: JSON.stringify({ course_id: courseId ?? null }),
    }),
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
