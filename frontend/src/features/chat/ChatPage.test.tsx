import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
