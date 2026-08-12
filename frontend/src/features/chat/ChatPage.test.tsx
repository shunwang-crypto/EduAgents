import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  createMemoryRouter,
  RouterProvider,
} from "react-router-dom";
import { ChatPage } from "./ChatPage";

const { mockApi, defaultChatReply } = vi.hoisted(() => {
  const defaultChatReply = {
    message_id: "MSG-1", conversation_id: "C-1", content: "**回答**",
    course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
    context: { type: "plan_step", course_id: "PY", plan_step_id: "S2", step_title: "DataFrame 基础" },
  };
  const mockApi = {
    listCourseCategories: vi.fn().mockResolvedValue([]),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
    getCourse: vi.fn((cid: string) =>
      Promise.resolve({
        course_id: cid,
        display_name: cid === "JAVA" ? "Java OOP" : "Python 数据分析",
        category_id: null,
        current_goal: null,
      })
    ),
    getChat: vi.fn((cid: string, conv: string | null) =>
      Promise.resolve({ conversation_id: conv || "C-1", course_id: cid, messages: [] })
    ),
    getStep: vi.fn().mockResolvedValue({
      step_id: "S2", seq: 2, stage_id: "stage-2", stage_title: "核心学习",
      stage_order: 2, kc_id: "knowledge-2", title: "DataFrame 基础",
      description: "行列与索引", learning_objective: "能读写 DataFrame",
      prerequisites: [], difficulty: "中等", minutes: 45, status: "not_started",
    }),
    chat: vi.fn().mockResolvedValue(defaultChatReply),
  };
  return { mockApi, defaultChatReply };
});

vi.mock("../../api/ApiProvider", () => ({ useApi: () => mockApi }));

function renderChat(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/courses/:courseId/chat" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>
  );
}

// 可导航 router（用于跨课程切换的 stale-async 回归测试）
function renderNavigableChat(initialPath: string) {
  const router = createMemoryRouter(
    [{ path: "/courses/:courseId/chat", element: <ChatPage /> }],
    { initialEntries: [initialPath] }
  );
  render(<RouterProvider router={router} />);
  return router;
}

// 可控 deferred Promise：模拟「请求已发出但尚未 resolve」再切换课程
function deferred<T = unknown>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("ChatPage plan step context", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows context chip when ?step= is present", async () => {
    renderChat("/courses/PY/chat?step=S2");
    await waitFor(() => expect(screen.getByText(/学习计划 · DataFrame 基础/)).toBeTruthy());
  });

  it("does not show chip without ?step=", async () => {
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy());
    expect(screen.queryByText(/学习计划 ·/)).toBeNull();
  });

  it("loads conversation from ?conversation= query", async () => {
    renderChat("/courses/PY/chat?conversation=CONV-NEW");
    await waitFor(() =>
      expect(mockApi.getChat as ReturnType<typeof vi.fn>).toHaveBeenCalledWith("PY", "CONV-NEW")
    );
  });
});

describe("ChatPage send / retry", () => {
  beforeEach(() => vi.clearAllMocks());

  async function sendText(text: string) {
    const input = await screen.findByLabelText("消息输入框");
    const sendBtn = screen.getByRole("button", { name: "发送" });
    fireEvent.change(input, { target: { value: text } });
    fireEvent.click(sendBtn);
  }

  it("retry does not duplicate user bubble after failure", async () => {
    (mockApi.chat as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error("发送失败，请重试"))
      .mockResolvedValueOnce({
        message_id: "MSG-2", conversation_id: "C-1", content: "**回答**",
        course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
        context: { type: "course", course_id: "PY", plan_step_id: null, step_title: "" },
      });
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy());
    await sendText("解释 Attention");
    // 失败：错误提示 + 用户消息只有 1 条
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getAllByText("解释 Attention").length).toBe(1);
    // 重试成功：用户消息仍只有 1 条
    fireEvent.click(screen.getByText("重试"));
    await waitFor(() => expect(screen.getByText("回答")).toBeTruthy());
    expect(screen.getAllByText("解释 Attention").length).toBe(1);
  });

  it("conversation id from reply is used for subsequent sends", async () => {
    (mockApi.chat as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        message_id: "MSG-1", conversation_id: "CONV-NEW", content: "第一答",
        course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
        context: { type: "course", course_id: "PY", plan_step_id: null, step_title: "" },
      })
      .mockResolvedValueOnce({
        message_id: "MSG-2", conversation_id: "CONV-NEW", content: "第二答",
        course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
        context: { type: "course", course_id: "PY", plan_step_id: null, step_title: "" },
      });
    renderChat("/courses/PY/chat");
    await waitFor(() => expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy());
    await sendText("你好");
    await waitFor(() => expect(screen.getByText("第一答")).toBeTruthy());
    await sendText("继续");
    await waitFor(() => expect(screen.getByText("第二答")).toBeTruthy());
    const calls = (mockApi.chat as ReturnType<typeof vi.fn>).mock.calls;
    // 第二次发送携带第一次返回的 conversation_id（URL 已写回）
    expect(calls[1][0].conversation_id).toBe("CONV-NEW");
  });

  it("cross-course: pending chat(A) then switch B does not mutate B", async () => {
    const chatDefer = deferred<typeof defaultChatReply>();
    (mockApi.chat as ReturnType<typeof vi.fn>).mockReturnValue(chatDefer.promise);
    const router = renderNavigableChat("/courses/PY/chat");
    try {
      await waitFor(() =>
        expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy()
      );
      // 在 A 上发送消息
      const input = screen.getByLabelText("消息输入框");
      fireEvent.change(input, { target: { value: "解释 Attention" } });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() =>
        expect((mockApi.chat as ReturnType<typeof vi.fn>)).toHaveBeenCalled()
      );
      // 切换到 B（JAVA）
      await act(async () => { router.navigate("/courses/JAVA/chat"); });
      await waitFor(() =>
        expect(screen.getByPlaceholderText(/继续问关于 Java OOP/)).toBeTruthy()
      );
      // 解析迟到的 A 回复：应被 scope 守卫丢弃
      await act(async () => {
        chatDefer.resolve({
          message_id: "MSG-A", conversation_id: "C-A", content: "**A的回答**",
          course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
          context: { type: "course", course_id: "PY", plan_step_id: "", step_title: "" },
        });
      });
      // B 不应显示 A 的回答
      await waitFor(() => expect(screen.queryByText("A的回答")).toBeNull());
      // B 的 URL 不应包含 A 的 conversation（stale 写回被拦截）
      expect(router.state.location.search).not.toContain("C-A");
    } finally {
      (mockApi.chat as ReturnType<typeof vi.fn>).mockResolvedValue(defaultChatReply);
    }
  });

  it("conversation switch: pending reply from CONV-A does not mutate CONV-B", async () => {
    const chatDefer = deferred<typeof defaultChatReply>();
    (mockApi.chat as ReturnType<typeof vi.fn>).mockReturnValue(chatDefer.promise);
    const router = renderNavigableChat("/courses/PY/chat?conversation=CONV-A");
    try {
      await waitFor(() => expect(screen.getByPlaceholderText(/继续问关于 Python 数据分析/)).toBeTruthy());
      const input = screen.getByLabelText("消息输入框");
      fireEvent.change(input, { target: { value: "A 请求" } });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() => expect(mockApi.chat).toHaveBeenCalled());

      await act(async () => { router.navigate("/courses/PY/chat?conversation=CONV-B"); });
      await waitFor(() => expect(mockApi.getChat).toHaveBeenCalledWith("PY", "CONV-B"));
      await act(async () => {
        chatDefer.resolve({
          message_id: "MSG-A", conversation_id: "CONV-A", content: "A 的迟到回答",
          course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
          context: { type: "course", course_id: "PY", plan_step_id: "", step_title: "" },
        });
      });
      await waitFor(() => expect(screen.queryByText("A 的迟到回答")).toBeNull());
      expect(router.state.location.search).toContain("CONV-B");
      expect(router.state.location.search).not.toContain("CONV-A");
    } finally {
      (mockApi.chat as ReturnType<typeof vi.fn>).mockResolvedValue(defaultChatReply);
    }
  });
});
