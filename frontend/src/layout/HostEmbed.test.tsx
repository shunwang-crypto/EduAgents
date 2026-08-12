import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";
import { render, waitFor, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LearningApp } from "../app/router";
// 与 LearningApp 内组件同一份 ApiError 类（同模块 → instanceof 成立）
import { ApiError } from "../api/ApiProvider";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourses: vi.fn().mockResolvedValue([
      { course_id: "PY", display_name: "Python 数据分析", category_id: null, current_goal: null },
    ]),
    listCourseCategories: vi.fn().mockResolvedValue([]),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析", category_id: null }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: "C-1", course_id: "PY", messages: [] }),
    getStep: vi.fn(),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    getPlan: vi.fn().mockRejectedValue(Object.assign(new Error("404"), { status: 404 })),
    createCourse: vi.fn(),
    updateStep: vi.fn(),
    generatePlan: vi.fn(),
    renameCourse: vi.fn(),
    deleteCourse: vi.fn(),
    chat: vi.fn(),
  },
}));

vi.mock("../api/ApiProvider", () => ({
  useApi: () => mockApi,
  ApiProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ApiError: class ApiError extends Error { status: number; constructor(status: number, m: string) { super(m); this.status = status; } },
}));

beforeAll(() => {
  // jsdom 无完整 matchMedia：AppShell 的 useMediaQuery 需要
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
});

/** 宿主嵌入：/host/learning/* 挂载 LearningApp，路由相对解析不跳宿主根。 */
describe("LearningApp host embedding", () => {
  beforeEach(() => vi.clearAllMocks());

  function renderHost(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/host/learning/*" element={<LearningApp userId="USER-A" />} />
        </Routes>
      </MemoryRouter>
    );
  }

  it("mounts at /host/learning/ and shows general chat empty state", async () => {
    renderHost("/host/learning/");
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
  });

  it("routes to course chat under /host/learning/courses/:id/chat", async () => {
    renderHost("/host/learning/courses/PY/chat");
    await waitFor(() => expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy());
  });

  it("routes to plan under /host/learning/courses/:id/plan (404 → empty plan state)", async () => {
    // StudyPlanPage 以 `e instanceof ApiError && e.status === 404` 判定空计划，需用真正的 ApiError
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new ApiError(404, "no plan"));
    renderHost("/host/learning/courses/PY/plan");
    await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
  });
});
