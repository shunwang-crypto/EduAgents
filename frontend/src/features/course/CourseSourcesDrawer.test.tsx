import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CourseSourcesDrawer } from "./CourseSourcesDrawer";
import { openCourseSources } from "./courseSourcesEvents";
import type { CourseSource } from "../../api/types";

/** 可控 deferred promise：手动 resolve，用于确定性模拟请求返回顺序。 */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourseSources: vi.fn(),
    addCourseSource: vi.fn(),
    deleteCourseSource: vi.fn(),
    searchCourseSources: vi.fn(),
  },
}));

vi.mock("../../api/ApiProvider", () => ({ useApi: () => mockApi }));

function src(id: string, title: string): CourseSource {
  return {
    source_id: id,
    user_id: "U",
    course_id: "C-A",
    source_type: "web",
    source_url: `https://e.com/${id}`,
    title,
    status: "ready",
    chunk_count: 1,
    error_message: "",
    created_at: "",
    updated_at: "",
  };
}

describe("CourseSourcesDrawer stale async", () => {
  beforeEach(() => vi.clearAllMocks());

  it("same-course latest load wins: late old response must not overwrite newest", async () => {
    const d1 = deferred<CourseSource[]>();
    const d2 = deferred<CourseSource[]>();
    const listFn = mockApi.listCourseSources as ReturnType<typeof vi.fn>;
    listFn.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise);
    (mockApi.addCourseSource as ReturnType<typeof vi.fn>).mockResolvedValue(src("S2", "New Source"));

    render(<CourseSourcesDrawer />);
    openCourseSources("C-A");
    // load #1 pending（d1 未 resolve）
    await waitFor(() => expect(listFn).toHaveBeenCalledTimes(1));

    // 添加成功后触发 load #2（d2 pending）
    fireEvent.change(screen.getByPlaceholderText("https://… （网页或 GitHub 仓库）"), {
      target: { value: "https://e.com/new" },
    });
    fireEvent.click(screen.getByRole("button", { name: /添加/ }));
    await waitFor(() => expect(listFn).toHaveBeenCalledTimes(2));

    // 新响应先返回 → [New Source]
    d2.resolve([src("S2", "New Source")]);
    await waitFor(() => expect(screen.getByText("New Source")).toBeTruthy());

    // 旧响应（#1）后返回 [] → 必须被 latest-wins 丢弃，不得覆盖
    d1.resolve([]);
    await waitFor(() => expect(screen.getByText("New Source")).toBeTruthy());
    expect(screen.queryByText("还没有资料")).toBeNull();
  });

  it("cross-course stale: resolving course A after opening B must not show A data", async () => {
    const dA = deferred<CourseSource[]>();
    const dB = deferred<CourseSource[]>();
    const listFn = mockApi.listCourseSources as ReturnType<typeof vi.fn>;
    listFn.mockReturnValueOnce(dA.promise).mockReturnValueOnce(dB.promise);

    render(<CourseSourcesDrawer />);
    openCourseSources("C-A");
    await waitFor(() => expect(listFn).toHaveBeenCalledTimes(1));

    // 打开 B → scope invalidate + 新 load（dB pending）
    openCourseSources("C-B");
    await waitFor(() => expect(listFn).toHaveBeenCalledTimes(2));

    // A 的旧响应迟到 → 不得显示
    dA.resolve([src("SA", "Course A 资料")]);
    await waitFor(() => expect(screen.queryByText("Course A 资料")).toBeNull());

    // B 响应正常显示
    dB.resolve([src("SB", "Course B 资料")]);
    await waitFor(() => expect(screen.getByText("Course B 资料")).toBeTruthy());
  });
});
