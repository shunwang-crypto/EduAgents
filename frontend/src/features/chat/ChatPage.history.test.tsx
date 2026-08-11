import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ChatPage } from "./ChatPage";
// 从被 mock 的 ApiProvider 取出与 ChatPage 同一份 ApiError 类（同模块 → instanceof 成立）
import { ApiError } from "../../api/ApiProvider";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
    getChat: vi.fn(),
    getStep: vi.fn(),
    chat: vi.fn(),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-NEW", course_id: null }),
  },
}));

// ApiError 必须在 factory 内联定义（vi.mock 提升后无法引用文件顶层 import）。
// ChatPage 通过 `instanceof ApiError` 区分 404/500/网络错误，故注入的错误必须是同一类实例。
vi.mock("../../api/ApiProvider", () => ({
  useApi: () => mockApi,
  ApiProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, m: string) {
      super(m);
      this.status = status;
    }
  },
}));

function renderChat(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/courses/:courseId/chat" element={<ChatPage />} />
        <Route path="/" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ChatPage history load states", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fresh course: GET returns empty messages → empty state, no error", async () => {
    (mockApi.getChat as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: null,
      course_id: "PY",
      messages: [],
    });
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByText("今天想学习什么？")).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("history 404 → 该对话不存在或已失效 + 开始新对话 (navigates to General Chat)", async () => {
    (mockApi.getChat as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new ApiError(404, "conversation not found"))
      .mockResolvedValueOnce({ conversation_id: null, course_id: null, messages: [] });
    renderChat("/courses/PY/chat?conversation=STALE");
    await waitFor(() => expect(screen.getByText("该对话不存在或已失效")).toBeTruthy());
    const startBtn = screen.getByText("开始新对话");
    fireEvent.click(startBtn);
    // 新建 General Chat 会话（course_id=null）
    await waitFor(() =>
      expect((mockApi.createConversation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null)
    );
    // 离开错配的课程路由：以 course_id=null 重新加载，而非停留在 PY
    await waitFor(() =>
      expect((mockApi.getChat as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(null, "CONV-NEW")
    );
  });

  it("history 500 → 无法加载历史消息 + 重试", async () => {
    (mockApi.getChat as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new ApiError(500, "internal error"))
      .mockResolvedValueOnce({ conversation_id: null, course_id: "PY", messages: [] });
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByText("无法加载历史消息")).toBeTruthy());
    fireEvent.click(screen.getByText("重试"));
    await waitFor(() =>
      expect((mockApi.getChat as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2)
    );
  });

  it("network error (non-ApiError) → 无法加载历史消息 + 重试", async () => {
    (mockApi.getChat as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("network down"));
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByText("无法加载历史消息")).toBeTruthy());
    expect(screen.getByText("重试")).toBeTruthy();
  });
});
