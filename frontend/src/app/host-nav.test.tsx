import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LearningApp } from "./router";

const { mockPlan } = vi.hoisted(() => ({
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
      {
        stage_id: "stage-2",
        stage_title: "核心学习",
        order: 2,
        steps: [
          {
            step_id: "S2", seq: 2, stage_id: "stage-2", stage_title: "核心学习",
            stage_order: 2, kc_id: "knowledge-2", title: "DataFrame 基础",
            description: "行列与索引", learning_objective: "能读写 DataFrame",
            prerequisites: [], difficulty: "中等", minutes: 45, status: "not_started",
          },
        ],
      },
      {
        stage_id: "stage-3",
        stage_title: "综合应用",
        order: 3,
        steps: [
          {
            step_id: "S3", seq: 3, stage_id: "stage-3", stage_title: "综合应用",
            stage_order: 3, kc_id: "knowledge-3", title: "数据清洗案例",
            description: "小项目", learning_objective: "完成清洗流程",
            prerequisites: [], difficulty: "实践", minutes: 60, status: "not_started",
          },
        ],
      },
    ],
  },
}));

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourses: vi.fn().mockResolvedValue([]),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: null, course_id: null, messages: [] }),
    getStep: vi.fn().mockImplementation((_c: string, stepId: string) =>
      Promise.resolve({
        step_id: stepId, seq: 1, stage_id: "stage-1", stage_title: "基础", stage_order: 1,
        kc_id: "k1", title: stepId === "S1" ? "NumPy 数组基础" : "步骤",
        description: "", learning_objective: "", prerequisites: [], difficulty: "入门",
        minutes: 30, status: "not_started",
      })
    ),
    chat: vi.fn(),
    getPlan: vi.fn().mockResolvedValue(mockPlan),
    generatePlan: vi.fn().mockResolvedValue(mockPlan),
    updateStep: vi.fn().mockResolvedValue(mockPlan),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "C", course_id: null }),
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

function renderHost(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/host/learning/*" element={<LearningApp userId="USER-A" />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("host-relative navigation (CourseHeader tabs + Plan Step)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("CourseHeader 学习计划 tab from course chat → /host/learning/courses/PY/plan (host-relative)", async () => {
    renderHost("/host/learning/courses/PY/chat");
    await waitFor(() => expect(screen.getByText("对话")).toBeTruthy());
    fireEvent.click(screen.getByText("学习计划"));
    await waitFor(() => expect(screen.getByText("阶段 1")).toBeTruthy());
  });

  it("Plan Step 就此提问 → /host/learning/courses/PY/chat?step=S1 (host-relative)", async () => {
    renderHost("/host/learning/courses/PY/plan");
    await waitFor(() => expect(screen.getAllByText("就此提问").length).toBe(3));
    fireEvent.click(screen.getAllByText("就此提问")[0]);
    await waitFor(() => expect(screen.getByText(/学习计划 · NumPy 数组基础/)).toBeTruthy());
  });
});
