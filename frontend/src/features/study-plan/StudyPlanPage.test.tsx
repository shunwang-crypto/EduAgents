import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  createMemoryRouter,
  RouterProvider,
} from "react-router-dom";
import { StudyPlanPage } from "./StudyPlanPage";

// vi.mock factory 会被提升到文件顶部，mock 数据必须用 vi.hoisted 定义
const { mockPlan, mockApi } = vi.hoisted(() => {
  const mockPlan = {
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
  };
  const mockApi = {
    getCourse: vi.fn((cid: string) =>
      Promise.resolve({
        course_id: cid,
        display_name: cid === "JAVA" ? "Java OOP" : "Python 数据分析",
        duration_days: 14,
        daily_minutes: 60,
      })
    ),
    // 参数感知：课程切换测试需要按 courseId 返回对应课程计划
    getPlan: vi.fn((cid: string) =>
      Promise.resolve(
        cid === "JAVA"
          ? { ...mockPlan, course_id: "JAVA", title: "Java OOP 学习计划" }
          : mockPlan
      )
    ),
    generatePlan: vi.fn().mockResolvedValue(mockPlan),
    updateStep: vi.fn().mockResolvedValue(mockPlan),
    getLesson: vi.fn((_cid: string, stepId: string) =>
      Promise.resolve({
        step_id: stepId,
        lesson_markdown: "## 本节要学什么\nNumPy 数组是…",
        lesson_generated_at: "2026-08-11T00:00:00Z",
        title: "NumPy 数组基础",
      })
    ),
  };
  return { mockPlan, mockApi };
});

vi.mock("../../api/ApiProvider", () => ({ useApi: () => mockApi }));

function renderPage(initialPath = "/courses/PY/plan") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
      </Routes>
    </MemoryRouter>
  );
}

// 可导航 router（用于跨课程切换的 stale-async 回归测试）
function renderNavigablePlan(initialPath: string) {
  const router = createMemoryRouter(
    [{ path: "/courses/:courseId/plan", element: <StudyPlanPage /> }],
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

describe("StudyPlanPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders exactly 3 stage sections", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("阶段 1")).toBeTruthy());
    expect(screen.getByText("阶段 2")).toBeTruthy();
    expect(screen.getByText("阶段 3")).toBeTruthy();
    expect(screen.getByText("基础准备")).toBeTruthy();
    expect(screen.getByText("核心学习")).toBeTruthy();
    expect(screen.getByText("综合应用")).toBeTruthy();
  });

  it("every stage has at least one step", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("NumPy 数组基础")).toBeTruthy());
    expect(screen.getByText("DataFrame 基础")).toBeTruthy();
    expect(screen.getByText("数据清洗案例")).toBeTruthy();
  });

  it("renders step learning objective and prerequisites (compact metadata)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("能创建数组")).toBeTruthy());
    // compact metadata：label「目标 / 前置」与内容分属两个 span
    expect(screen.getAllByText("目标").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Python List")).toBeTruthy();
    expect(screen.getByText("前置")).toBeTruthy();
  });

  it("shows 就此提问 button per step", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("就此提问").length).toBe(3));
  });

  it("three-state step buttons: not_started shows 开始学习", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
  });

  it("clicking 开始学习 calls updateStep with in_progress", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    const btn = screen.getAllByText("开始学习")[0];
    fireEvent.click(btn);
    await waitFor(() =>
      expect((mockApi.updateStep as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY", "S1", "in_progress"
      )
    );
  });

  it("expands full markdown plan via 查看完整说明", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("查看完整说明")).toBeTruthy());
    fireEvent.click(screen.getByText("查看完整说明"));
    // RichMarkdown 渲染 markdown 的 h2「完整计划」
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "完整计划" })).toBeTruthy()
    );
    expect(screen.getByText("收起完整说明")).toBeTruthy();
  });

  it("shows empty state when no plan", async () => {
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    renderPage();
    await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
  });

  it("clicking 开始学习 expands lesson panel and lazily loads it", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    fireEvent.click(screen.getAllByText("开始学习")[0]);
    // 展开后出现「标记完成」与「收起」
    await waitFor(() => expect(screen.getByText("标记完成")).toBeTruthy());
    expect(screen.getByText("收起")).toBeTruthy();
    // Lesson 懒加载完成（getLesson mock 返回的 Markdown 渲染出标题）
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "本节要学什么" })).toBeTruthy()
    );
    // getLesson 仅调用一次（缓存）
    expect((mockApi.getLesson as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });

  it("clicking 标记完成 calls updateStep with completed", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    fireEvent.click(screen.getAllByText("开始学习")[0]);
    await waitFor(() => expect(screen.getByText("标记完成")).toBeTruthy());
    fireEvent.click(screen.getByText("标记完成"));
    await waitFor(() =>
      expect((mockApi.updateStep as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        "S1",
        "completed"
      )
    );
  });

  it("shows plan settings inputs initialized from course and applies them on regenerate", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("计划设置")).toBeTruthy());
    const dur = screen.getByDisplayValue("14") as HTMLInputElement;
    const min = screen.getByDisplayValue("60") as HTMLInputElement;
    expect(dur).toBeTruthy();
    expect(min).toBeTruthy();
    // 改每日时长为 90
    fireEvent.change(min, { target: { value: "90" } });
    // 重新生成并确认
    fireEvent.click(screen.getByText("重新生成计划"));
    fireEvent.click(screen.getByText("确认重新生成"));
    await waitFor(() =>
      expect((mockApi.generatePlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        expect.objectContaining({ duration_days: 14, daily_minutes: 90 })
      )
    );
  });

  it("hides step description when it equals the title (dedup)", async () => {
    const dupPlan = {
      ...mockPlan,
      stages: [
        {
          stage_id: "s1",
          stage_title: "基础",
          order: 1,
          steps: [
            {
              step_id: "D1",
              seq: 1,
              stage_id: "s1",
              stage_title: "基础",
              stage_order: 1,
              kc_id: "k",
              title: "相同标题",
              description: "相同标题",
              learning_objective: "",
              prerequisites: [],
              difficulty: "入门",
              minutes: 20,
              status: "not_started",
            },
          ],
        },
      ],
    };
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(dupPlan);
    renderPage();
    await waitFor(() => expect(screen.getByText("相同标题")).toBeTruthy());
    // 标题出现一次；描述与标题相同则不重复渲染
    expect(screen.getAllByText("相同标题").length).toBe(1);
  });

  it("empty plan shows settings inputs initialized from course and applies them on first generate", async () => {
    (mockApi.getCourse as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      course_id: "PY",
      display_name: "Python 数据分析",
      duration_days: 21,
      daily_minutes: 45,
    });
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    renderPage();
    await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
    // 输入初始值来自课程已保存设置 21/45
    const dur = screen.getByDisplayValue("21") as HTMLInputElement;
    const min = screen.getByDisplayValue("45") as HTMLInputElement;
    expect(dur).toBeTruthy();
    expect(min).toBeTruthy();
    // 改为 30/90 并填写当前基础
    fireEvent.change(dur, { target: { value: "30" } });
    fireEvent.change(min, { target: { value: "90" } });
    fireEvent.change(screen.getByPlaceholderText("例如：我会基础 Python"), {
      target: { value: "我会基础 Python" },
    });
    fireEvent.click(screen.getByText("生成学习计划"));
    await waitFor(() =>
      expect((mockApi.generatePlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        expect.objectContaining({
          duration_days: 30,
          daily_minutes: 90,
          background: "我会基础 Python",
        })
      )
    );
  });

  it("cross-course: pending updateStep(A) then switch B does not mutate B (A)", async () => {
    const upDefer = deferred<typeof mockPlan>();
    (mockApi.updateStep as ReturnType<typeof vi.fn>).mockReturnValue(upDefer.promise);
    const router = renderNavigablePlan("/courses/PY/plan");
    try {
      await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
      // 在 A 上点「开始学习」→ toggleStep(A) 发出（pending）
      fireEvent.click(screen.getAllByText("开始学习")[0]);
      await waitFor(() =>
        expect((mockApi.updateStep as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
          "PY", "S1", "in_progress"
        )
      );
      // 切换到 B（JAVA）
      await act(async () => { router.navigate("/courses/JAVA/plan"); });
      await waitFor(() =>
        expect((mockApi.getPlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("JAVA")
      );
      // 解析迟到的 A 响应：应被 scope 守卫丢弃
      await act(async () => { upDefer.resolve(mockPlan); });
      // B 页面不应显示 A 的计划标题
      await waitFor(() =>
        expect(screen.queryByText("Python 数据分析 学习计划")).toBeNull()
      );
      // 旧 toggleStep(A) 过期 → 返回 false → 不会触发 openLesson(A)
      expect(
        (mockApi.getLesson as ReturnType<typeof vi.fn>).mock.calls.some((c) => c[0] === "PY")
      ).toBe(false);
    } finally {
      (mockApi.updateStep as ReturnType<typeof vi.fn>).mockResolvedValue(mockPlan);
    }
  });

  it("cross-course: pending generatePlan(A) then switch B does not mutate B (B)", async () => {
    const genDefer = deferred<typeof mockPlan>();
    (mockApi.generatePlan as ReturnType<typeof vi.fn>).mockReturnValue(genDefer.promise);
    // EMPTY 课程返回无计划，进入 empty 态
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockImplementation((cid: string) =>
      Promise.resolve(
        cid === "EMPTY"
          ? null
          : cid === "JAVA"
            ? { ...mockPlan, course_id: "JAVA", title: "Java OOP 学习计划" }
            : mockPlan
      )
    );
    const router = renderNavigablePlan("/courses/EMPTY/plan");
    try {
      await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
      fireEvent.click(screen.getByText("生成学习计划"));
      await waitFor(() =>
        expect((mockApi.generatePlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
          "EMPTY", expect.objectContaining({})
        )
      );
      // 切换到 B（JAVA）
      await act(async () => { router.navigate("/courses/JAVA/plan"); });
      await waitFor(() =>
        expect((mockApi.getPlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("JAVA")
      );
      // 解析迟到的 A 生成响应：应被 scope 守卫丢弃
      await act(async () => { genDefer.resolve(mockPlan); });
      // B 页面应显示自己的计划，且不应被 A 的计划污染
      await waitFor(() => expect(screen.getByText("Java OOP 学习计划")).toBeTruthy());
      expect(screen.queryByText("Python 数据分析 学习计划")).toBeNull();
    } finally {
      (mockApi.generatePlan as ReturnType<typeof vi.fn>).mockResolvedValue(mockPlan);
      (mockApi.getPlan as ReturnType<typeof vi.fn>).mockImplementation((cid: string) =>
        Promise.resolve(
          cid === "JAVA"
            ? { ...mockPlan, course_id: "JAVA", title: "Java OOP 学习计划" }
            : mockPlan
        )
      );
    }
  });

  it("cross-course: pending openLesson(A) then switch B does not show A lesson (C)", async () => {
    const lessonDefer = deferred<{
      step_id: string; lesson_markdown: string; lesson_generated_at: string; title: string;
    }>();
    (mockApi.getLesson as ReturnType<typeof vi.fn>).mockReturnValue(lessonDefer.promise);
    const router = renderNavigablePlan("/courses/PY/plan");
    try {
      await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
      // 点「开始学习」：toggleStep 默认 resolve → 触发 openLesson(PY)（pending）
      fireEvent.click(screen.getAllByText("开始学习")[0]);
      await waitFor(() =>
        expect((mockApi.getLesson as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("PY", "S1")
      );
      // 切换到 B（JAVA）
      await act(async () => { router.navigate("/courses/JAVA/plan"); });
      await waitFor(() =>
        expect((mockApi.getPlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("JAVA")
      );
      // 解析迟到的 A lesson
      await act(async () => {
        lessonDefer.resolve({
          step_id: "S1",
          lesson_markdown: "## 本节要学什么\nPY专属讲解",
          lesson_generated_at: "2026-08-11T00:00:00Z",
          title: "NumPy 数组基础",
        });
      });
      // B 页面不应出现 A 的 lesson 内容（stale 保护仍有效）
      await waitFor(() => expect(screen.queryByText("PY专属讲解")).toBeNull());
    } finally {
      (mockApi.getLesson as ReturnType<typeof vi.fn>).mockResolvedValue({
        step_id: "S1",
        lesson_markdown: "## 本节要学什么\nNumPy 数组是…",
        lesson_generated_at: "2026-08-11T00:00:00Z",
        title: "NumPy 数组基础",
      });
    }
  });
});
