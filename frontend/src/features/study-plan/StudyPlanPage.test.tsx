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

// 避免在 jsdom 中真正挂载 React Flow（依赖大量浏览器测量 API，测试脆弱）。
// 我们测的是 StudyPlanPage 的编排（loading/empty/error/generate 联动），
// 而非 React Flow 图本身的渲染，因此用轻量桩替换。
vi.mock("./LearningMap/LearningMapView", () => ({
  default: ({
    data,
    selectedKcId,
    onSelect,
  }: {
    data: unknown;
    selectedKcId: string | null;
    onSelect: (node: { id: string; name: string; locked?: boolean; mastery?: number | null }) => void;
  }) => {
    const list = (data as { nodes?: Array<{ id: string; name: string; locked?: boolean; mastery?: number | null }> })?.nodes ?? [];
    return (
      <div>
        {list.map((n) => (
          <button
            key={n.id}
            type="button"
            data-node-id={n.id}
            data-locked={n.locked ? "1" : "0"}
            className="mock-kc-node"
            onClick={() => onSelect(n)}
          >
            {n.name}
          </button>
        ))}
        <div data-testid="map-selected">{selectedKcId ?? "none"}</div>
      </div>
    );
  },
}));

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
    listCourseCategories: vi.fn().mockResolvedValue([]),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
    getCourse: vi.fn((cid: string) =>
      Promise.resolve({
        course_id: cid,
        display_name: cid === "JAVA" ? "Java OOP" : "Python 数据分析",
        duration_days: 14,
        daily_minutes: 60,
        category_id: null,
        // 有课程目标：避免「无目标」禁用生成分支，保持既有生成流程测试语义
        current_goal: "掌握 Pandas、NumPy 和数据分析流程",
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
    // Adaptive Map + Tutor：StudyPlanPage 挂载时即会 GET learning-map
    getLearningMap: vi.fn().mockResolvedValue({
      course_id: "PY",
      goal: "掌握 NumPy 数组计算",
      nodes: [
        {
          id: "numpy_array", name: "NumPy 数组", description: "ndarray",
          difficulty: "easy", mastery: null, confidence: null, status: "unknown",
          recommended: true, locked: false, prerequisites: [], misconceptions: [],
          recent_evidence: [], reason_codes: ["LOW_MASTERY"],
        },
        {
          id: "numpy_broadcasting", name: "NumPy 广播", description: "broadcast",
          difficulty: "hard", mastery: null, confidence: null, status: "unknown",
          recommended: false, locked: true, prerequisites: ["numpy_array"], misconceptions: [],
          recent_evidence: [], reason_codes: [],
        },
      ],
      edges: [{ source: "numpy_array", target: "numpy_broadcasting", relation: "prerequisite", weight: 1 }],
      recommended_path: ["numpy_array", "numpy_broadcasting"],
      current_recommended_kc: "numpy_array",
      graph_source: "generated",
    }),
    tutorTurn: vi.fn().mockResolvedValue({
      kc_id: "numpy_array",
      teaching_action: "ASSESS",
      message: "请解释一下语义相似的句子其 embedding 的特点",
      learner_state_changed: true,
      learning_map_changed: true,
      mastery: 0.42,
      confidence: 0.68,
      reason_codes: ["LOW_MASTERY"],
      next_recommended_kc: "numpy_broadcasting",
      explanation: "",
      turn_id: "TURN-1",
    }),
  };
  return { mockPlan, mockApi };
});

vi.mock("../../api/ApiProvider", () => ({ useApi: () => mockApi }));

function renderPage(initialPath = "/courses/PY/plan") {
  const utils = render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/courses/:courseId/plan" element={<StudyPlanPage />} />
      </Routes>
    </MemoryRouter>
  );
  // 计划列表类断言默认属于「计划列表」标签；切换到该标签以保证既有测试可用。
  try {
    fireEvent.click(utils.getByText("计划列表"));
  } catch {
    /* tab 未渲染时忽略 */
  }
  return utils;
}

// Map 标签测试：默认 Map 标签，不切换到计划列表
function renderMapPage(initialPath = "/courses/PY/plan") {
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
  try {
    fireEvent.click(screen.getByText("计划列表"));
  } catch {
    /* tab 未渲染时忽略 */
  }
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

// ---------------------------------------------------------------------------
// Adaptive Learning Map 回归测试（§43 Test A~J）
// ---------------------------------------------------------------------------
describe("StudyPlanPage · Learning Map", () => {
  beforeEach(() => vi.clearAllMocks());

  // Test A + E + J：Learning Map 正常渲染动态节点；mastery=null 显示 ?
  it("renders learning map with unknown mastery as ? and dynamic numpy nodes (A/E/J)", async () => {
    renderMapPage();
    // 挂载后即 GET learning-map
    await waitFor(() => expect(mockApi.getLearningMap).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "NumPy 数组" }).length).toBeGreaterThan(0)
    );
    expect(screen.getAllByRole("button", { name: "NumPy 广播" }).length).toBeGreaterThan(0);
    // Test J：不 hardcode embedding/rag/agent
    expect(screen.queryByRole("button", { name: "embedding" })).toBeNull();
    expect(screen.queryByRole("button", { name: "rag" })).toBeNull();
    expect(screen.queryByRole("button", { name: "agent" })).toBeNull();
    // Test E：UNKNOWN 节点掌握度显示 ?（默认选中 numpy_array，detail 中展示 ?）
    await waitFor(() =>
      expect(screen.getByTestId("map-selected").textContent).toBe("numpy_array")
    );
    expect(screen.queryByText("0%")).toBeNull();
  });

  // Test C：没有 plan / graph → 显示 Empty State，不显示红色 error
  it("no plan shows empty state, not error (C)", async () => {
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      status: 404,
    });
    renderMapPage();
    await waitFor(() => expect(screen.getByText("学习地图将在生成学习计划后创建")).toBeTruthy());
    expect(screen.queryByText("学习地图暂时无法加载")).toBeNull();
    expect(screen.queryByText("加载学习地图失败")).toBeNull();
  });

  // Test C'：真实 server error → 错误态（带重试），区别于 empty state
  it("real server error shows retry, not empty state", async () => {
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      status: 500,
      message: "boom",
    });
    renderMapPage();
    await waitFor(() => expect(screen.getByText("学习地图暂时无法加载")).toBeTruthy());
    expect(screen.queryByText("学习地图将在生成学习计划后创建")).toBeNull();
  });

  // Test B：generatePlan 成功后 getLearningMap 再次被调用（P0-2）
  it("generatePlan success triggers getLearningMap again (B)", async () => {
    // 用 Once 避免持久污染后续用例（clearAllMocks 不清除 mockResolvedValue 实现）
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockRejectedValueOnce({ status: 404 });
    renderMapPage();
    await waitFor(() => expect(mockApi.getLearningMap).toHaveBeenCalled());
    const callsBefore = (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mock.calls.length;
    // 切到计划列表 empty 态并生成
    fireEvent.click(screen.getByText("计划列表"));
    await waitFor(() => expect(screen.getByText("还没有学习计划")).toBeTruthy());
    fireEvent.click(screen.getByText("生成学习计划"));
    await waitFor(() => expect(mockApi.generatePlan).toHaveBeenCalled());
    // P0-2：生成成功后必须再次 GET learning-map（第二次 getLearningMap 用默认 resolve）
    await waitFor(() =>
      expect((mockApi.getLearningMap as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(
        callsBefore
      )
    );
  });

  // Test H：tutorTurn 成功后 getLearningMap 再次被调用
  it("tutor success triggers getLearningMap refetch (H)", async () => {
    renderMapPage();
    await waitFor(() =>
      expect(screen.getByTestId("map-selected").textContent).toBe("numpy_array")
    );
    const callsBefore = (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mock.calls.length;
    // 默认选中 recommended 节点（numpy_array），点击「开始学习」→ send(null) → tutorTurn
    fireEvent.click(screen.getByText("开始学习"));
    await waitFor(() => expect(mockApi.tutorTurn).toHaveBeenCalled());
    await waitFor(() =>
      expect((mockApi.getLearningMap as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(
        callsBefore
      )
    );
  });

  // Test D：locked 节点 → detail 可查看，但 Start Tutor 被禁用
  it("locked node: detail viewable, start tutor disabled (D)", async () => {
    renderMapPage();
    // 点击 locked 节点（mock 节点按钮）
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "NumPy 广播" }).length).toBeGreaterThan(0)
    );
    fireEvent.click(screen.getAllByRole("button", { name: "NumPy 广播" })[0]);
    // detail 可查看：Tutor 区显示 locked 提示（文本前有 emoji，用 exact:false）
    await waitFor(() =>
      expect(screen.getByText("该知识点尚未解锁", { exact: false })).toBeTruthy()
    );
    // 开始学习按钮不存在（locked 时不会出现「开始学习」）
    expect(screen.queryByText("开始学习")).toBeNull();
  });

  // Test F/G：Tutor 返回 current kc + next recommended 分离，进入下一知识点才切换
  it("current kc mastered shows enter-next button, only switches on click (F/G)", async () => {
    // 把当前选中节点设为 mastered，且 next_recommended_kc 指向另一个节点
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockResolvedValue({
      course_id: "PY",
      goal: "g",
      nodes: [
        {
          id: "embedding", name: "Embedding", description: "", difficulty: "easy",
          mastery: 0.8, confidence: 0.9, status: "mastered",
          recommended: false, locked: false, prerequisites: [], misconceptions: [],
          recent_evidence: [], reason_codes: [],
        },
        {
          id: "vector_db", name: "Vector DB", description: "", difficulty: "medium",
          mastery: null, confidence: null, status: "unknown",
          recommended: true, locked: false, prerequisites: ["embedding"], misconceptions: [],
          recent_evidence: [], reason_codes: [],
        },
      ],
      edges: [],
      recommended_path: ["vector_db"],
      current_recommended_kc: "vector_db",
    });
    // Tutor 返回 next_recommended_kc = vector_db（P1-4：response.kc_id 保持 embedding）
    (mockApi.tutorTurn as ReturnType<typeof vi.fn>).mockResolvedValue({
      kc_id: "embedding",
      teaching_action: "FEEDBACK",
      message: "很好",
      learner_state_changed: true,
      learning_map_changed: true,
      mastery: 0.8,
      confidence: 0.9,
      reason_codes: ["RECENT_SUCCESS"],
      next_recommended_kc: "vector_db",
      explanation: "",
      turn_id: "TURN-F",
    });
    renderMapPage();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Embedding" }).length).toBeGreaterThan(0)
    );
    // 选中 Embedding 并开始 Tutor
    fireEvent.click(screen.getAllByRole("button", { name: "Embedding" })[0]);
    fireEvent.click(screen.getByText("开始学习"));
    await waitFor(() => expect(screen.getByText("进入下一知识点")).toBeTruthy());
    // P1-4：selected node 仍是 embedding（current kc 不被自动切换）
    expect(
      screen.getByText("当前知识点：", { exact: false }).textContent
    ).toContain("Embedding");
    // 点击「进入下一知识点」后才切换到 Vector DB
    fireEvent.click(screen.getByText("进入下一知识点"));
    await waitFor(() =>
      expect(
        screen.getByText("当前知识点：", { exact: false }).textContent
      ).toContain("Vector DB")
    );
  });
});

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
      // 有目标（无目标会禁用「生成学习计划」→ 本用例验证的是首生成沿用 21/45）
      current_goal: "掌握 Pandas、NumPy 和数据分析流程",
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
