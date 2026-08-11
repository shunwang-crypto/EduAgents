import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ChatPage } from "./ChatPage";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: "C-1", course_id: "PY", messages: [] }),
    getStep: vi.fn().mockResolvedValue({
      step_id: "S2", seq: 2, stage_id: "stage-2", stage_title: "核心学习",
      stage_order: 2, kc_id: "knowledge-2", title: "DataFrame 基础",
      description: "行列与索引", learning_objective: "能读写 DataFrame",
      prerequisites: [], difficulty: "中等", minutes: 45, status: "not_started",
    }),
    chat: vi.fn().mockResolvedValue({
      message_id: "MSG-1", conversation_id: "C-1", content: "**回答**",
      course_id: "PY", created_at: "2026-08-11T00:00:00Z", profile_updates: [],
      context: { type: "plan_step", course_id: "PY", plan_step_id: "S2", step_title: "DataFrame 基础" },
    }),
  },
}));

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
});
