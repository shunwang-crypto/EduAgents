import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StudyPlanPage } from "./StudyPlanPage";
import { ApiProvider } from "../../api/ApiProvider";

// 模块级 mock client 类型：避免在 vi.hoisted / vi.mock 工厂作用域之间互相引用内部函数
type MockApiClient = {
  userId: string;
  getCourse: ReturnType<typeof vi.fn>;
  getPlan: ReturnType<typeof vi.fn>;
  generatePlan: ReturnType<typeof vi.fn>;
  updateStep: ReturnType<typeof vi.fn>;
  getLesson: ReturnType<typeof vi.fn>;
  chat: ReturnType<typeof vi.fn>;
  listCourses: ReturnType<typeof vi.fn>;
  getChat: ReturnType<typeof vi.fn>;
  getStep: ReturnType<typeof vi.fn>;
  createConversation: ReturnType<typeof vi.fn>;
};

const { mockPlan, clients } = vi.hoisted(() => ({
  mockPlan: {
    plan_id: "PLAN-1",
    course_id: "PY",
    goal_id: "G-1",
    title: "Python 数据分析 学习计划",
    summary: "14 天 · 每天 60 分钟",
    plan_markdown: "## 完整计划\n\n- 步骤",
    progress: 0,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    steps: [],
    stages: [
      {
        stage_id: "stage-1",
        stage_title: "基础准备",
        order: 1,
        steps: [
          {
            step_id: "S1", seq: 1, stage_id: "stage-1", stage_title: "基础准备",
            stage_order: 1, kc_id: "knowledge-1", title: "NumPy 数组基础",
            description: "理解 ndarray", learning_objective: "能创建数组",
            prerequisites: [], difficulty: "入门", minutes: 30, status: "not_started",
          },
        ],
      },
    ],
  },
  clients: new Map<string, MockApiClient>(),
}));

// mock createApiClient：每个 userId 返回独立 client 实例（ApiProvider 内部 useMemo(userId)）。
// 用于验证切换 userId 后 StudyPlanPage 的 generate/toggleStep 拿到的是新 api（无 stale closure）。
vi.mock("../../api/client", () => {
  const make = (userId: string): MockApiClient => ({
    userId,
    getCourse: vi.fn().mockResolvedValue({
      course_id: "PY", display_name: "Python 数据分析",
      category_id: null, current_goal: "掌握 Pandas、NumPy 和数据分析流程",
    }),
    getPlan: vi.fn().mockResolvedValue(mockPlan),
    generatePlan: vi.fn().mockResolvedValue(mockPlan),
    updateStep: vi.fn().mockResolvedValue(mockPlan),
    chat: vi.fn(),
    listCourses: vi.fn().mockResolvedValue([]),
    getChat: vi.fn().mockResolvedValue({ conversation_id: null, course_id: null, messages: [] }),
    getStep: vi.fn(),
    getLesson: vi.fn().mockResolvedValue({
      step_id: "S1",
      lesson_markdown: "## 本节要学什么\nNumPy 数组是…",
      lesson_generated_at: "2026-08-11T00:00:00Z",
      title: "NumPy 数组基础",
    }),
    createConversation: vi.fn(),
  });
  return {
    createApiClient: vi.fn((userId: string) => {
      if (!clients.has(userId)) clients.set(userId, make(userId));
      return clients.get(userId)!;
    }),
    ApiError: class ApiError extends Error {
      status: number;
      constructor(s: number, m: string) {
        super(m);
        this.status = s;
      }
    },
  };
});

function renderWith(userId: string) {
  return render(
    <MemoryRouter initialEntries={["/courses/PY/plan"]}>
      <ApiProvider userId={userId}>
        <Routes>
          <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
        </Routes>
      </ApiProvider>
    </MemoryRouter>
  );
}

describe("StudyPlanPage uses fresh api after userId swap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clients.clear();
  });

  it("generate with A uses client A; after swap to B uses client B only (no stale closure)", async () => {
    const { rerender } = renderWith("USER-A");
    await waitFor(() => expect(screen.getByText("阶段 1")).toBeTruthy());
    // ready 态的入口是「重新生成计划」→ 确认弹层「确认重新生成」（empty 态才是「生成学习计划」）
    fireEvent.click(screen.getByText("重新生成计划"));
    fireEvent.click(screen.getByText("确认重新生成"));
    await waitFor(() => expect((clients.get("USER-A")!.generatePlan)).toHaveBeenCalled());
    expect((clients.get("USER-B")?.generatePlan as ReturnType<typeof vi.fn> | undefined)).toBeUndefined();

    rerender(
      <MemoryRouter initialEntries={["/courses/PY/plan"]}>
        <ApiProvider userId="USER-B">
          <Routes>
            <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
          </Routes>
        </ApiProvider>
      </MemoryRouter>
    );
    // 切换 userId 后 effect 重跑：用新 client B 重新 getPlan
    await waitFor(() => expect((clients.get("USER-B")!.getPlan)).toHaveBeenCalled());
    // ready 态的入口是「重新生成计划」→ 确认弹层「确认重新生成」（empty 态才是「生成学习计划」）
    fireEvent.click(screen.getByText("重新生成计划"));
    fireEvent.click(screen.getByText("确认重新生成"));
    await waitFor(() => expect((clients.get("USER-B")!.generatePlan)).toHaveBeenCalled());

    // 关键回归：切换后再 generate 不应再调用旧 client A（stale closure 会落到 A）
    expect((clients.get("USER-A")!.generatePlan as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    expect((clients.get("USER-B")!.generatePlan as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });
});
