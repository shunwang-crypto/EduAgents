import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StudyPlanPage } from "./StudyPlanPage";

// vi.mock factory 会被提升到文件顶部，mock 数据必须用 vi.hoisted 定义
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
            prerequisites: ["Python List"], difficulty: "入门", minutes: 30,
            status: "not_started",
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
            prerequisites: [], difficulty: "中等", minutes: 45,
            status: "not_started",
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
            prerequisites: [], difficulty: "实践", minutes: 60,
            status: "not_started",
          },
        ],
      },
    ],
  },
}));

vi.mock("../../api/client", () => ({
  api: {
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
    getPlan: vi.fn().mockResolvedValue(mockPlan),
    generatePlan: vi.fn().mockResolvedValue(mockPlan),
    updateStep: vi.fn().mockResolvedValue(mockPlan),
  },
}));

function renderPage(initialPath = "/courses/PY/plan") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("StudyPlanPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders exactly 3 stage sections", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/学习计划/)).toBeTruthy());
    const titles = screen.getAllByText(/基础准备|核心学习|综合应用/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("1. 基础准备")).toBeTruthy();
    expect(screen.getByText("2. 核心学习")).toBeTruthy();
    expect(screen.getByText("3. 综合应用")).toBeTruthy();
  });

  it("every stage has at least one step", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("NumPy 数组基础")).toBeTruthy());
    expect(screen.getByText("DataFrame 基础")).toBeTruthy();
    expect(screen.getByText("数据清洗案例")).toBeTruthy();
  });

  it("renders step learning objective and prerequisites", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/目标：能创建数组/)).toBeTruthy());
    expect(screen.getByText(/前置：Python List/)).toBeTruthy();
  });

  it("shows 就此提问 button per step", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("就此提问").length).toBe(3));
  });

  it("expands full markdown plan via 查看完整计划", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("查看完整计划")).toBeTruthy());
    fireEvent.click(screen.getByText("查看完整计划"));
    // RichMarkdown 渲染 markdown 的 h2「完整计划」
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "完整计划" })).toBeTruthy()
    );
    expect(screen.getByText("收起完整计划")).toBeTruthy();
  });

  it("shows empty state when no plan", async () => {
    const { api } = await import("../../api/client");
    (api.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    renderPage();
    await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
  });
});
