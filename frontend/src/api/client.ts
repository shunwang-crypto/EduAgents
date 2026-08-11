/** API Client：Fetch 封装。user_id 由 createApiClient(userId) 注入（X-User-Id 头）。
 * 业务代码通过 ApiProvider 的 useApi() 获取实例，绝不写死任何用户。 */
import type {
  ChatResponse,
  Conversation,
  Course,
  PlanStep,
  StudyPlan,
} from "./types";

export interface ApiClient {
  // Courses
  listCourses: () => Promise<Course[]>;
  createCourse: (body: { topic: string; goal?: string; duration_days?: number; daily_minutes?: number }) => Promise<Course>;
  getCourse: (courseId: string) => Promise<Course>;
  renameCourse: (courseId: string, title: string) => Promise<Course>;
  deleteCourse: (courseId: string) => Promise<void>;

  // Study Plan
  generatePlan: (courseId: string, body: { goal?: string; duration_days?: number; daily_minutes?: number; background?: string }) => Promise<StudyPlan>;
  getPlan: (courseId: string) => Promise<StudyPlan>;
  updateStep: (courseId: string, stepId: string, status: string) => Promise<StudyPlan>;
  getStep: (courseId: string, stepId: string) => Promise<PlanStep>;

  // Chat
  createConversation: (courseId?: string | null) => Promise<{ conversation_id: string; course_id: string | null }>;
  chat: (body: {
    message: string;
    course_id?: string | null;
    conversation_id?: string | null;
    plan_step_id?: string | null;
  }) => Promise<ChatResponse>;
  getChat: (courseId?: string | null, conversationId?: string | null) => Promise<Conversation>;
}

/** 按 userId 创建 ApiClient（X-User-Id 头随请求发送）。
 * 每次 userId 变化都应创建新实例（ApiProvider 内部 useMemo）。 */
export function createApiClient(userId: string): ApiClient {
  const headers = (extra?: Record<string, string>) => ({
    "Content-Type": "application/json",
    "X-User-Id": userId,
    ...(extra ?? {}),
  });

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(path, {
      ...options,
      headers: headers(options.headers as Record<string, string> | undefined),
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

  return {
    // Courses
    listCourses: () => request<Course[]>("/api/courses"),
    createCourse: (body) =>
      request<Course>("/api/courses", { method: "POST", body: JSON.stringify(body) }),
    getCourse: (courseId) => request<Course>(`/api/courses/${courseId}`),
    renameCourse: (courseId, title) =>
      request<Course>(`/api/courses/${courseId}`, { method: "PATCH", body: JSON.stringify({ title }) }),
    deleteCourse: (courseId) =>
      request<void>(`/api/courses/${courseId}`, { method: "DELETE" }),

    // Study Plan
    generatePlan: (courseId, body) =>
      request<StudyPlan>(`/api/courses/${courseId}/plan/generate`, { method: "POST", body: JSON.stringify(body) }),
    getPlan: (courseId) => request<StudyPlan>(`/api/courses/${courseId}/plan`),
    updateStep: (courseId, stepId, status) =>
      request<StudyPlan>(`/api/courses/${courseId}/plan/steps/${stepId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    getStep: (courseId, stepId) =>
      request<PlanStep>(`/api/courses/${courseId}/plan/steps/${stepId}`),

    // Chat
    createConversation: (courseId) =>
      request<{ conversation_id: string; course_id: string | null }>("/api/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ course_id: courseId ?? null }),
      }),
    chat: (body) => request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify(body) }),
    getChat: (courseId, conversationId) =>
      request<Conversation>(
        `/api/chat?course_id=${courseId ?? ""}&conversation_id=${conversationId ?? ""}`
      ),
  };
}
