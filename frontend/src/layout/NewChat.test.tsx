import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { ChatPage } from "../features/chat/ChatPage";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourses: vi.fn().mockResolvedValue([]),
    listCourseCategories: vi.fn().mockResolvedValue([]),
    listConversations: vi.fn().mockResolvedValue([]),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: null, course_id: null, messages: [] }),
    getStep: vi.fn(),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-GENERAL", course_id: null }),
  },
}));

vi.mock("../api/ApiProvider", () => ({
  useApi: () => mockApi,
  ApiProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(s: number, m: string) {
      super(m);
      this.status = s;
    }
  },
}));

beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = ((q: string) =>
      ({
        matches: false,
        media: q,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown) as typeof window.matchMedia;
  }
});

function renderAt(initialEntry: string, hostPrefix = "") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path={`${hostPrefix}/*`} element={<AppShell />}>
          <Route path="" element={<ChatPage />} />
          <Route path="courses/:courseId/chat" element={<ChatPage />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe("New Chat navigates to General Chat (not course route)", () => {
  beforeEach(() => vi.clearAllMocks());

  // 注：分类导航后 workspace 视图无「新对话」按钮（root 视图才有），
  // 故从根路径进入点击（核心断言不变：createConversation(null) + getChat(null, CONV)）。
  it("from root → 新对话 lands on General Chat root (course_id=null)", async () => {
    renderAt("/");
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "新对话" }).length).toBeGreaterThanOrEqual(1)
    );
    fireEvent.click(screen.getAllByRole("button", { name: "新对话" })[0]);
    // General Chat 空状态出现（落在根路由）
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
    await waitFor(() =>
      expect((mockApi.createConversation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null)
    );
    // 关键回归：新对话是普通对话（course_id=null），不应以任何课程重新加载历史
    expect(mockApi.getChat).toHaveBeenCalledWith(null, "CONV-GENERAL");
    expect(mockApi.getChat).not.toHaveBeenCalledWith("PY", "CONV-GENERAL");
  });

  it("host mount (/host/learning) → 新对话 lands on /host/learning?conversation=CONV-GENERAL", async () => {
    renderAt("/host/learning", "/host/learning");
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "新对话" }).length).toBeGreaterThanOrEqual(1)
    );
    fireEvent.click(screen.getAllByRole("button", { name: "新对话" })[0]);
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
    await waitFor(() =>
      expect((mockApi.createConversation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null)
    );
    expect(mockApi.getChat).toHaveBeenCalledWith(null, "CONV-GENERAL");
    expect(mockApi.getChat).not.toHaveBeenCalledWith("PY", "CONV-GENERAL");
  });
});
