/** API Client：Fetch 封装。user_id 由 createApiClient(userId) 注入（X-User-Id 头）。
 * 业务代码通过 ApiProvider 的 useApi() 获取实例，绝不写死任何用户。 */
import type {
  ChatResponse,
  Conversation,
  ConversationSummary,
  Course,
  CourseCategory,
  CourseSource,
  LearningMapResponse,
  PlanStep,
  SourceSearchResult,
  StudyPlan,
  TutorResponse,
  TutorTurnRequest,
} from "./types";

/** API 错误：优先解析后端 JSON detail/message，不把 {"detail":...} 原文直接给用户。 */
export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface ApiClient {
  // Courses
  listCourses: () => Promise<Course[]>;
  createCourse: (body: {
    topic: string;
    goal?: string;
    duration_days?: number;
    daily_minutes?: number;
    category_id?: string | null;
  }) => Promise<Course>;
  getCourse: (courseId: string) => Promise<Course>;
  /** 字段级更新（PATCH）：display_name / category_id（显式 null = 移到未分类）/ goal（Active Goal）。 */
  renameCourse: (courseId: string, body: {
    display_name?: string;
    category_id?: string | null;
    goal?: string;
  }) => Promise<Course>;
  deleteCourse: (courseId: string) => Promise<void>;

  // Course Categories（纯组织层：整理用户创建的课程）
  listCourseCategories: () => Promise<CourseCategory[]>;
  createCourseCategory: (name: string) => Promise<CourseCategory>;
  renameCourseCategory: (categoryId: string, name: string) => Promise<CourseCategory>;
  deleteCourseCategory: (categoryId: string) => Promise<void>;

  // Study Plan
  generatePlan: (courseId: string, body: { goal?: string; duration_days?: number; daily_minutes?: number; background?: string }) => Promise<StudyPlan>;
  getPlan: (courseId: string) => Promise<StudyPlan>;
  updateStep: (courseId: string, stepId: string, status: string) => Promise<StudyPlan>;
  getStep: (courseId: string, stepId: string) => Promise<PlanStep>;
  getLesson: (
    courseId: string,
    stepId: string,
  ) => Promise<{ step_id: string; lesson_markdown: string; lesson_generated_at: string | null; title: string }>;

  // Chat
  createConversation: (courseId?: string | null) => Promise<{ conversation_id: string; course_id: string | null }>;
  chat: (body: {
    message: string;
    course_id?: string | null;
    conversation_id?: string | null;
    plan_step_id?: string | null;
  }) => Promise<ChatResponse>;
  getChat: (courseId?: string | null, conversationId?: string | null) => Promise<Conversation>;

  // Conversations（最近对话列表）
  listConversations: (courseId?: string | null, limit?: number) => Promise<ConversationSummary[]>;

  // Course Sources（Web / GitHub / Internet Search）
  listCourseSources: (courseId: string) => Promise<CourseSource[]>;
  addCourseSource: (
    courseId: string,
    body: { url: string; title?: string },
  ) => Promise<CourseSource>;
  deleteCourseSource: (courseId: string, sourceId: string) => Promise<void>;
  searchCourseSources: (courseId: string, q: string, limit?: number) => Promise<SourceSearchResult[]>;

  // Adaptive Learning Map + Tutor
  getLearningMap: (courseId: string) => Promise<LearningMapResponse>;
  tutorTurn: (courseId: string, req: TutorTurnRequest) => Promise<TutorResponse>;
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
    let res: Response;
    try {
      res = await fetch(path, {
        ...options,
        headers: headers(options.headers as Record<string, string> | undefined),
      });
    } catch (error) {
      console.error(`Network request failed: ${path}`, error);
      throw new ApiError(0, "无法连接服务，请稍后重试");
    }
    if (!res.ok) {
      let detail: string | undefined;
      let message = `请求失败（${res.status}）`;
      try {
        const body = await res.json();
        if (typeof body?.detail === "string") {
          detail = body.detail;
          message = body.detail;
        } else if (typeof body?.message === "string") {
          detail = body.message;
          message = body.message;
        }
      } catch {
        // 非 JSON 错误体：保留通用消息
      }
      throw new ApiError(res.status, message, detail);
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
    renameCourse: (courseId, body) =>
      request<Course>(`/api/courses/${courseId}`, { method: "PATCH", body: JSON.stringify(body) }),
    deleteCourse: (courseId) =>
      request<void>(`/api/courses/${courseId}`, { method: "DELETE" }),

    // Course Categories
    listCourseCategories: () => request<CourseCategory[]>("/api/course-categories"),
    createCourseCategory: (name) =>
      request<CourseCategory>("/api/course-categories", { method: "POST", body: JSON.stringify({ name }) }),
    renameCourseCategory: (categoryId, name) =>
      request<CourseCategory>(`/api/course-categories/${categoryId}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      }),
    deleteCourseCategory: (categoryId) =>
      request<void>(`/api/course-categories/${categoryId}`, { method: "DELETE" }),

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
    getLesson: (courseId, stepId) =>
      request<{ step_id: string; lesson_markdown: string; lesson_generated_at: string | null; title: string }>(
        `/api/courses/${courseId}/plan/steps/${stepId}/lesson`,
        { method: "POST" },
      ),

    // Chat
    createConversation: (courseId) =>
      request<{ conversation_id: string; course_id: string | null }>("/api/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ course_id: courseId ?? null }),
      }),
    chat: (body) => request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify(body) }),
    getChat: (courseId, conversationId) => {
      const params = new URLSearchParams();
      if (courseId) params.set("course_id", courseId);
      if (conversationId) params.set("conversation_id", conversationId);
      return request<Conversation>(`/api/chat?${params.toString()}`);
    },

    // Conversations
    listConversations: (courseId, limit = 6) => {
      const params = new URLSearchParams();
      if (courseId) params.set("course_id", courseId);
      params.set("limit", String(limit));
      return request<ConversationSummary[]>(`/api/chat/conversations?${params.toString()}`);
    },

    // Course Sources
    listCourseSources: (courseId) =>
      request<CourseSource[]>(`/api/courses/${courseId}/sources`),
    addCourseSource: (courseId, body) =>
      request<CourseSource>(`/api/courses/${courseId}/sources`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    deleteCourseSource: (courseId, sourceId) =>
      request<void>(`/api/courses/${courseId}/sources/${sourceId}`, { method: "DELETE" }),
    searchCourseSources: (courseId, q, limit = 5) => {
      const params = new URLSearchParams();
      params.set("q", q);
      params.set("limit", String(limit));
      return request<SourceSearchResult[]>(`/api/courses/${courseId}/sources/search?${params.toString()}`);
    },

    // Adaptive Learning Map + Tutor
    getLearningMap: (courseId) =>
      request<LearningMapResponse>(`/api/courses/${courseId}/learning-map`),
    tutorTurn: (courseId, req) =>
      request<TutorResponse>(`/api/courses/${courseId}/tutor/turn`, {
        method: "POST",
        body: JSON.stringify(req),
      }),
  };
}
