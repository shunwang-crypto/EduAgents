import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { ChatPage } from "../features/chat/ChatPage";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourses: vi.fn().mockResolvedValue([]),
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

  it("from course page → 新对话 lands on General Chat root (course_id=null)", async () => {
    renderAt("/courses/PY/chat");
    await waitFor(() => expect(screen.getByText("新对话")).toBeTruthy());
    fireEvent.click(screen.getByText("新对话"));
    // General Chat 空状态出现（落在根路由，而非 /courses/PY/chat）
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
    await waitFor(() =>
      expect((mockApi.createConversation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null)
    );
    // 关键回归：新对话是普通对话（course_id=null），不应仍以 PY 重新加载历史
    expect(mockApi.getChat).toHaveBeenCalledWith(null, "CONV-GENERAL");
    expect(mockApi.getChat).not.toHaveBeenCalledWith("PY", "CONV-GENERAL");
  });

  it("host mount (/host/learning) → 新对话 lands on /host/learning?conversation=CONV-GENERAL", async () => {
    renderAt("/host/learning/courses/PY/chat", "/host/learning");
    await waitFor(() => expect(screen.getByText("新对话")).toBeTruthy());
    fireEvent.click(screen.getByText("新对话"));
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
    await waitFor(() =>
      expect((mockApi.createConversation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null)
    );
    expect(mockApi.getChat).toHaveBeenCalledWith(null, "CONV-GENERAL");
    expect(mockApi.getChat).not.toHaveBeenCalledWith("PY", "CONV-GENERAL");
  });
});
