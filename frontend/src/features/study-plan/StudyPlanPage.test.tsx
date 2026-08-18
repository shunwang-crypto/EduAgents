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
    plan_brief: {
      course_id: "PY",
      plan_id: "P-1",
      goal: "掌握 Pandas、NumPy 和数据分析流程",
      target_outcome: "独立完成数据分析流程",
      why_this_plan: ["你已经具备：基础 Python", "当前主要能力缺口：NumPy"],
      stage_overview: [],
      critical_path: [
        { kc_id: "knowledge-1", name: "NumPy 数组基础" },
        { kc_id: "knowledge-2", name: "数据分析" },
        { kc_id: "knowledge-3", name: "Pandas" },
      ],
      difficulty_hotspots: [],
      known_skills: [],
      skill_gaps: [],
      unassessed_skills: ["NumPy 数组基础", "数据分析"],
      adaptation_rules: [],
      time_budget: "",
    },
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
    getExplanation: vi.fn((_cid: string, _planId: string, stepId: string) =>
      Promise.resolve({
        step_id: stepId,
        plan_id: "P-1",
        kc_id: "knowledge-1",
        title: "NumPy 数组基础",
        objective: "能创建数组",
        estimated_minutes: 30,
        blocks: [
          { type: "orientation", title: "为什么现在学它？", content: "前置知识", data: {}, source_refs: [] },
          { type: "big_picture", title: "先看整体", content: "", data: { items: ["NumPy 数组"] }, source_refs: [] },
          { type: "concept", title: "核心概念", content: "ndarray 表示数据", data: {}, source_refs: [] },
        ],
        context_hash: "hash-1",
        generated_at: "2026-08-11T00:00:00Z",
      })
    ),
    getPlanBrief: vi.fn().mockResolvedValue({
      course_id: "PY",
      plan_id: "P-1",
      goal: "掌握 Pandas、NumPy 和数据分析流程",
      target_outcome: "独立完成数据分析流程",
      why_this_plan: [],
      stage_overview: [],
      critical_path: [],
      difficulty_hotspots: [],
      known_skills: [],
      skill_gaps: [],
      adaptation_rules: [],
      time_budget: "",
    }),
    getPracticeHandoff: vi.fn().mockResolvedValue({
      course_id: "PY", plan_id: "P-1", step_id: "S1", kc_id: "knowledge-1",
      learning_objective: "能创建数组", recommended_difficulty: "easy",
      source: "study_plan", return_url: "",
    }),
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
      recommended_candidates: [],
      active_path: ["numpy_array", "numpy_broadcasting"],
      graph_source: "generated",
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

  // 重构后：TutorPanel 不再属于 StudyPlan 主页面（§52-53）。主页面无「发送答案/提问」输入。
  it("study plan main page has no chat/tutor input (was TutorPanel)", async () => {
    renderMapPage();
    await waitFor(() => expect(mockApi.getLearningMap).toHaveBeenCalled());
    // 不出现 Tutor 聊天式输入框
    expect(screen.queryByPlaceholderText(/请输入你的回答/)).toBeNull();
    expect(screen.queryByText("智能导师")).toBeNull();
  });

  // §54：生产 UI 不泄露内部工程概念
  it("no internal terminology leaks in visible UI", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    const body = document.body.textContent ?? "";
    for (const leaked of [
      "KC:",
      "kc_",
      "UNKNOWN_STATE",
      "GOAL_RELEVANT",
      "NEXT_IN_PLAN",
      "PREREQUISITE_",
      "Learner Model",
      "Practice module",
      "Structured Explanation",
      "知识组件",
      "Knowledge Component",
    ]) {
      expect(body).not.toContain(leaked);
    }
  });

  // §62：Plan List / Detail / PlanBrief 不显示 raw id
  it("no raw kc_ ids in plan list and detail", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    const body = document.body.textContent ?? "";
    expect(body.match(/kc_[a-z0-9]+/)).toBeNull();
  });

  // §35/§61：选择 Map 节点出现「开始讲解」CTA，点击进入 Explanation Workspace
  it("selecting map node shows 开始讲解 CTA and opens workspace", async () => {
    // 用与 plan step 匹配的 kc_id（knowledge-1），保证 findPlanStepForKc 命中（Once 避免污染后续用例）
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      course_id: "PY", goal: "g",
      nodes: [
        { id: "knowledge-1", name: "NumPy 数组基础", description: "", difficulty: "easy",
          mastery: null, confidence: null, status: "unknown", recommended: true, locked: false,
          prerequisites: [], misconceptions: [], recent_evidence: [], reason_codes: [] },
        { id: "knowledge-2", name: "DataFrame 基础", description: "", difficulty: "easy",
          mastery: null, confidence: null, status: "unknown", recommended: false, locked: false,
          prerequisites: ["knowledge-1"], misconceptions: [], recent_evidence: [], reason_codes: [] },
      ],
      edges: [{ source: "knowledge-1", target: "knowledge-2", relation: "prerequisite", weight: 1 }],
      recommended_path: ["knowledge-1"],
      current_recommended_kc: "knowledge-1",
      recommended_candidates: [], active_path: ["knowledge-1"],
    });
    renderMapPage();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "NumPy 数组基础" }).length).toBeGreaterThan(0)
    );
    fireEvent.click(screen.getAllByRole("button", { name: "NumPy 数组基础" })[0]);
    // 右侧出现讲解 CTA（该 KC 对应 step 未开始 → 开始讲解）
    await waitFor(() => expect(screen.getByText("开始讲解")).toBeTruthy());
    fireEvent.click(screen.getByText("开始讲解"));
    // 进入 Explanation Workspace
    await waitFor(() => expect(screen.getByText("第 1 / 3 部分")).toBeTruthy());
  });

  // §43/§56：PlanBrief 显示「尚待评估」（UNKNOWN 不进能力缺口）
  it("plan brief shows 尚待评估 for unknown skills", async () => {
    (mockApi.getLearningMap as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      course_id: "PY", goal: "g",
      nodes: [
        { id: "k1", name: "K1", description: "", difficulty: "easy", mastery: null,
          confidence: null, status: "unknown", recommended: true, locked: false,
          prerequisites: [], misconceptions: [], recent_evidence: [], reason_codes: [] },
      ],
      edges: [], recommended_path: ["k1"], current_recommended_kc: "k1",
      recommended_candidates: [], active_path: ["k1"],
    });
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ...mockPlan,
      plan_brief: {
        ...mockPlan.plan_brief,
        critical_path: [{ kc_id: "k1", name: "K1" }],
        known_skills: [], skill_gaps: [], unassessed_skills: ["K1"],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("尚待评估")).toBeTruthy());
    expect(screen.queryByText("建议加强")).toBeNull();
    expect(screen.queryByText("已确认掌握")).toBeNull();
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
    // PlanBrief 关键路径与步骤标题可能同名 → 用 getAllByText
    await waitFor(() =>
      expect(screen.getAllByText("NumPy 数组基础").length).toBeGreaterThan(0)
    );
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

  // 重构后：Plan List 不再展开长文 Lesson（§16），而是打开结构化讲解 Workspace。
  it("clicking 开始学习 opens Explanation Workspace (not lesson article)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    fireEvent.click(screen.getAllByText("开始学习")[0]);
    // 打开结构化讲解：出现分块导航 + 首个 block 标题，而非 Markdown 长文
    await waitFor(() => expect(screen.getByText("第 1 / 3 部分")).toBeTruthy());
    expect(screen.getAllByText("为什么现在学它？").length).toBeGreaterThan(0);
    // 不出现聊天式输入框（TutorPanel 已移除）
    expect(screen.queryByPlaceholderText(/请输入你的回答/)).toBeNull();
    // 不直接在列表内展开整篇 lesson markdown（无「本节要学什么」标题）
    expect(screen.queryByRole("heading", { name: "本节要学什么" })).toBeNull();
  });

  // 点击「下一部分」可以逐块浏览（不是一篇文章 / 不是 chat 时间轴）
  it("explanation navigates block by block", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
    fireEvent.click(screen.getAllByText("开始学习")[0]);
    await waitFor(() => expect(screen.getByText("第 1 / 3 部分")).toBeTruthy());
    fireEvent.click(screen.getByText("下一部分"));
    await waitFor(() => expect(screen.getByText("第 2 / 3 部分")).toBeTruthy());
    expect(screen.getAllByText("先看整体").length).toBeGreaterThan(0);
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
      // 旧 toggleStep(A) 过期 → 返回 false → 不会触发 openExplanation(A)
      expect(
        (mockApi.getExplanation as ReturnType<typeof vi.fn>).mock.calls.some((c) => c[0] === "PY")
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

  it("cross-course: pending openExplanation(A) then switch B does not show A explanation (C)", async () => {
    const expDefer = deferred<{
      step_id: string; plan_id: string; kc_id: string; title: string;
      objective: string; estimated_minutes: number;
      blocks: Array<{ type: string; title: string; content: string; data: unknown; source_refs: string[] }>;
      context_hash: string; generated_at: string;
    }>();
    (mockApi.getExplanation as ReturnType<typeof vi.fn>).mockReturnValue(expDefer.promise);
    const router = renderNavigablePlan("/courses/PY/plan");
    try {
      await waitFor(() => expect(screen.getAllByText("开始学习").length).toBe(3));
      // 点「开始学习」：toggleStep 默认 resolve → 触发 openExplanation(PY)（pending）
      fireEvent.click(screen.getAllByText("开始学习")[0]);
      await waitFor(() =>
        expect((mockApi.getExplanation as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
          "PY", "PLAN-1", "S1"
        )
      );
      // 切换到 B（JAVA）
      await act(async () => { router.navigate("/courses/JAVA/plan"); });
      await waitFor(() =>
        expect((mockApi.getPlan as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("JAVA")
      );
      // 解析迟到的 A explanation
      await act(async () => {
        expDefer.resolve({
          step_id: "S1", plan_id: "P-1", kc_id: "knowledge-1",
          title: "NumPy 数组基础", objective: "能创建数组", estimated_minutes: 30,
          blocks: [{ type: "concept", title: "PY专属概念", content: "A课程讲解", data: {}, source_refs: [] }],
          context_hash: "hash", generated_at: "2026-08-11T00:00:00Z",
        });
      });
      // B 页面不应出现 A 的讲解内容（stale 保护仍有效）
      await waitFor(() => expect(screen.queryByText("PY专属概念")).toBeNull());
    } finally {
      (mockApi.getExplanation as ReturnType<typeof vi.fn>).mockResolvedValue({
        step_id: "S1", plan_id: "P-1", kc_id: "knowledge-1",
        title: "NumPy 数组基础", objective: "能创建数组", estimated_minutes: 30,
        blocks: [{ type: "concept", title: "核心概念", content: "ndarray", data: {}, source_refs: [] }],
        context_hash: "hash-1", generated_at: "2026-08-11T00:00:00Z",
      });
    }
  });
});
