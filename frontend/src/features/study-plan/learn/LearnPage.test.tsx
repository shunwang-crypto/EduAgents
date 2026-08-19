import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, useParams } from "react-router-dom";
import { LearnPage } from "./LearnPage";

// vi.mock factory 被提升到文件顶部，mock 数据必须用 vi.hoisted 定义
const { mockApi, explanationOf } = vi.hoisted(() => {
  const step = (over: Record<string, unknown> = {}) => ({
    step_id: "S1", seq: 1, stage_id: "stage-1", stage_title: "基础准备",
    stage_order: 1, kc_id: "knowledge-1", title: "NumPy 数组基础",
    description: "理解 ndarray", learning_objective: "能创建数组",
    prerequisites: ["Python List"], difficulty: "入门", minutes: 30,
    status: "not_started",
    ...over,
  });
  const mockPlan = {
    plan_id: "PLAN-1",
    course_id: "PY",
    goal_id: "G-1",
    title: "Python 数据分析 学习计划",
    summary: "14 天 · 每天 60 分钟",
    plan_markdown: "",
    progress: 0,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    steps: [],
    stages: [
      { stage_id: "stage-1", stage_title: "基础准备", order: 1, steps: [step()] },
      {
        stage_id: "stage-2", stage_title: "核心学习", order: 2,
        steps: [step({ step_id: "S2", seq: 2, stage_id: "stage-2", stage_title: "核心学习",
          stage_order: 2, kc_id: "knowledge-2", title: "DataFrame 基础", status: "completed" })],
      },
    ],
  };
  /** 5 节讲解：验证「一次性完整渲染」而不是卡片翻页。 */
  const explanationOf = (stepId: string) => ({
    step_id: stepId,
    plan_id: "PLAN-1",
    kc_id: "knowledge-1",
    title: "NumPy 数组基础",
    objective: "能创建数组",
    estimated_minutes: 25,
    blocks: [
      { type: "orientation", title: "为什么现在学它？", content: "它是数组计算的起点", data: {}, source_refs: [] },
      { type: "diagram", title: "它在知识网络中的位置", content: "",
        data: { nodes: [{ id: "list", label: "Python List" }, { id: "nd", label: "ndarray" }],
                edges: [{ source: "list", target: "nd" }] }, source_refs: [] },
      { type: "concept", title: "核心概念与 mental model", content: "ndarray 是同类型元素的多维容器", data: {}, source_refs: [] },
      { type: "misconception", title: "易混淆点", content: "别把视图当拷贝", data: {}, source_refs: [] },
      { type: "recap", title: "总结", content: "", data: { points: ["形状决定广播行为"] }, source_refs: [] },
    ],
    context_hash: "hash-1",
    generated_at: "2026-08-11T00:00:00Z",
  });
  const mockApi = {
    getCourse: vi.fn((cid: string) =>
      Promise.resolve({
        course_id: cid,
        display_name: cid === "JAVA" ? "Java OOP" : "Python 数据分析",
        duration_days: 14, daily_minutes: 60, category_id: null,
        current_goal: "掌握 Pandas、NumPy 和数据分析流程",
      })
    ),
    getPlan: vi.fn((cid: string) =>
      Promise.resolve(
        cid === "JAVA" ? { ...mockPlan, course_id: "JAVA", title: "Java OOP 学习计划" } : mockPlan
      )
    ),
    updateStep: vi.fn().mockResolvedValue(mockPlan),
    getExplanation: vi.fn((_cid: string, _planId: string, stepId: string) =>
      Promise.resolve(explanationOf(stepId))
    ),
  };
  return { mockApi, explanationOf };
});

vi.mock("../../../api/ApiProvider", () => ({ useApi: () => mockApi }));

/** 学习地图页桩：验证「返回学习地图」确实回到 plan 页。 */
function PlanRouteStub() {
  const { courseId } = useParams();
  return <div data-testid="plan-route">{`plan:${courseId}`}</div>;
}

function renderLearn(initialPath = "/courses/PY/learn/S1") {
  const router = createMemoryRouter(
    [
      { path: "/courses/:courseId/learn/:stepId", element: <LearnPage /> },
      { path: "/courses/:courseId/plan", element: <PlanRouteStub /> },
    ],
    { initialEntries: [initialPath] }
  );
  render(<RouterProvider router={router} />);
  return router;
}

function deferred<T = unknown>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("LearnPage（独立讲解页）", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the whole document at once: no card paging, TOC only navigates", async () => {
    renderLearn();
    await waitFor(() =>
      expect(screen.getAllByText("核心概念与 mental model").length).toBeGreaterThan(0)
    );
    // 所有 section 同时在文档里（长文档 + 自然滚动）
    for (const title of ["为什么现在学它？", "它在知识网络中的位置", "易混淆点", "总结"]) {
      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    }
    // 目录 5 项，正文 5 节
    expect(document.querySelectorAll(".explanation-toc-item").length).toBe(5);
    expect(document.querySelectorAll(".explanation-block-section").length).toBe(5);
    // 不再有卡片翻页
    expect(screen.queryByText("下一部分")).toBeNull();
    expect(screen.queryByText("上一部分")).toBeNull();
    expect(screen.queryByText(/第 \d+ \/ \d+ 部分/)).toBeNull();
    // 结构化图示按流程图渲染
    expect(document.querySelectorAll(".exp-flow-node").length).toBe(2);
  });

  it("clicking a TOC item scrolls to the matching section", async () => {
    const scrollSpy = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    try {
      renderLearn();
      await waitFor(() => expect(document.querySelectorAll(".explanation-toc-item").length).toBe(5));
      const items = document.querySelectorAll(".explanation-toc-item");
      fireEvent.click(items[3]);
      expect(scrollSpy).toHaveBeenCalled();
      const target = scrollSpy.mock.instances[0] as unknown as HTMLElement;
      expect(target.dataset.sectionIndex).toBe("3");
      // 目录只反映位置，内容不被切走
      expect(items[3].getAttribute("aria-current")).toBe("location");
      expect(screen.getAllByText("为什么现在学它？").length).toBeGreaterThan(0);
    } finally {
      scrollSpy.mockRestore();
    }
  });

  it("entering the page moves a not_started step to in_progress exactly once", async () => {
    renderLearn();
    await waitFor(() =>
      expect(mockApi.updateStep as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
        "PY", "S1", "in_progress"
      )
    );
    await waitFor(() =>
      expect(screen.getAllByText("核心概念与 mental model").length).toBeGreaterThan(0)
    );
    // plan 刷新回来后不得重复 PATCH
    expect((mockApi.updateStep as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });

  it("does not touch step status for an already completed step", async () => {
    renderLearn("/courses/PY/learn/S2");
    await waitFor(() => expect(screen.getByText("本节讲解已完成")).toBeTruthy());
    expect(mockApi.updateStep as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
    expect(screen.getByText("已完成")).toBeTruthy();
  });

  it("完成本节讲解 only updates PlanStep completion (mastery untouched)", async () => {
    renderLearn();
    await waitFor(() => expect(screen.getByText("完成本节讲解")).toBeTruthy());
    // 底部两个动作互不替代
    expect(screen.getByText("进入相关实践")).toBeTruthy();
    expect(screen.getByText(/完成讲解只记录学习进度/)).toBeTruthy();
    fireEvent.click(screen.getByText("完成本节讲解"));
    await waitFor(() =>
      expect(mockApi.updateStep as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
        "PY", "S1", "completed"
      )
    );
    // 只走 PlanStep 状态接口，没有任何掌握度写入路径
    const called = Object.keys(mockApi).filter(
      (k) => (mockApi as Record<string, ReturnType<typeof vi.fn>>)[k].mock.calls.length > 0
    );
    expect(called.sort()).toEqual(["getCourse", "getExplanation", "getPlan", "updateStep"]);
    await waitFor(() => expect(screen.getByText("本节讲解已完成")).toBeTruthy());
  });

  it("进入相关实践 is a separate action and does not complete the section", async () => {
    renderLearn();
    await waitFor(() => expect(screen.getByText("进入相关实践")).toBeTruthy());
    fireEvent.click(screen.getByText("进入相关实践"));
    await waitFor(() => expect(screen.getByText(/相关实践功能暂未开放/)).toBeTruthy());
    expect(mockApi.updateStep as ReturnType<typeof vi.fn>).not.toHaveBeenCalledWith(
      "PY", "S1", "completed"
    );
    expect(screen.getByText("完成本节讲解")).toBeTruthy();
  });

  it("返回学习地图 goes back to the plan page", async () => {
    renderLearn();
    await waitFor(() => expect(screen.getAllByText("返回学习地图").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText("返回学习地图")[0]);
    await waitFor(() => expect(screen.getByTestId("plan-route").textContent).toBe("plan:PY"));
  });

  it("shows a recoverable state when the step is not in the plan", async () => {
    renderLearn("/courses/PY/learn/GONE");
    await waitFor(() => expect(screen.getByText("找不到这个学习内容")).toBeTruthy());
    expect(mockApi.getExplanation as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
    // 顶部与缺失态各有一个返回入口，点缺失态里的那个
    fireEvent.click(screen.getAllByRole("button", { name: "返回学习地图" })[1]);
    await waitFor(() => expect(screen.getByTestId("plan-route").textContent).toBe("plan:PY"));
  });

  it("cross-course: pending explanation(A) then switch to B never shows A content", async () => {
    const expDefer = deferred<ReturnType<typeof explanationOf>>();
    (mockApi.getExplanation as ReturnType<typeof vi.fn>).mockReturnValueOnce(expDefer.promise);
    const router = renderLearn("/courses/PY/learn/S1");
    await waitFor(() =>
      expect(mockApi.getExplanation as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
        "PY", "PLAN-1", "S1"
      )
    );
    await act(async () => {
      router.navigate("/courses/JAVA/learn/S1");
    });
    await waitFor(() =>
      expect(mockApi.getPlan as ReturnType<typeof vi.fn>).toHaveBeenCalledWith("JAVA")
    );
    // A 课程的迟到响应必须被丢弃
    await act(async () => {
      expDefer.resolve({
        ...explanationOf("S1"),
        blocks: [{ type: "concept", title: "PY专属概念", content: "A课程讲解", data: {}, source_refs: [] }],
      });
    });
    await waitFor(() => expect(screen.queryByText("PY专属概念")).toBeNull());
    expect(screen.getAllByText("核心概念与 mental model").length).toBeGreaterThan(0);
  });

  it("surfaces a plan-level error without breaking the back entry", async () => {
    (mockApi.getPlan as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    renderLearn();
    await waitFor(() => expect(screen.getByText("无法加载学习计划，请重试")).toBeTruthy());
    expect(screen.getAllByText("返回学习地图").length).toBeGreaterThan(0);
  });
});
