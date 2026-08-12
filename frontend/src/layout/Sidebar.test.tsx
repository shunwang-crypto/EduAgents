import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

const { mockApi } = vi.hoisted(() => {
  const courses = [
    { course_id: "PY", display_name: "Python 数据分析" },
    { course_id: "JAVA", display_name: "Java OOP" },
    { course_id: "TRANSFORMER", display_name: "Transformer" },
  ];
  const mockApi = {
    listCourses: vi.fn().mockResolvedValue(courses),
    listConversations: vi.fn().mockResolvedValue([
      {
        conversation_id: "CONV-GEN-1",
        course_id: null,
        title: "多头注意力怎么理解",
        updated_at: "2026-08-12T10:00:00Z",
      },
    ]),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    createCourse: vi.fn(),
    renameCourse: vi
      .fn()
      .mockResolvedValue({ course_id: "PY", display_name: "Python 进阶" }),
    deleteCourse: vi.fn().mockResolvedValue(undefined),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
  };
  return { mockApi };
});

// 返回严格同一个 object reference：Sidebar 的 useEffect([api]) 依赖 api 引用稳定性，
// 引用不变则 rerender 不触发 load()，rename/delete 的本地 state 更新不会被 fixture 重新加载覆盖。
vi.mock("../api/ApiProvider", () => ({
  useApi: () => mockApi,
}));

function renderSidebar(props: Partial<React.ComponentProps<typeof Sidebar>> = {}) {
  return render(
    <MemoryRouter>
      <Sidebar
        open={false}
        collapsed={false}
        onClose={() => {}}
        onToggleCollapse={() => {}}
        newChat={() => {}}
        navigateToCourse={() => {}}
        {...props}
      />
    </MemoryRouter>
  );
}

describe("Sidebar", () => {
  beforeEach(() => vi.clearAllMocks());

  it("root shows new chat, courses entry, and recent conversations", async () => {
    renderSidebar();

    await waitFor(() =>
      expect(screen.getByText("多头注意力怎么理解")).toBeTruthy()
    );

    expect(screen.getByText("新对话")).toBeTruthy();
    expect(screen.getByText("课程")).toBeTruthy();
    expect(screen.getByText("最近")).toBeTruthy();

    // Root 不应直接展示课程列表
    expect(screen.queryByText("Python 数据分析")).toBeNull();
  });

  it("opens course list from the courses entry", async () => {
    renderSidebar();

    fireEvent.click(
      screen.getByRole("button", { name: "课程" })
    );

    await waitFor(() =>
      expect(screen.getByText("Python 数据分析")).toBeTruthy()
    );

    expect(screen.getByText("Java OOP")).toBeTruthy();
  });

  it("active course via useLocation gets aria-current (no popstate listener)", async () => {
    render(
      <MemoryRouter initialEntries={["/courses/PY/chat"]}>
        <Sidebar
          open={false}
          collapsed={false}
          onClose={() => {}}
          onToggleCollapse={() => {}}
          newChat={() => {}}
          navigateToCourse={() => {}}
        />
      </MemoryRouter>
    );
    // 课程列表需先点「课程」进入（Root 不再直接展示课程）
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    const pyBtn = screen.getByText("Python 数据分析").closest("button");
    expect(pyBtn?.getAttribute("aria-current")).toBe("page");
    const javaBtn = screen.getByText("Java OOP").closest("button");
    expect(javaBtn?.getAttribute("aria-current")).toBeNull();
  });

  it("collapsed shows only top-level actions, not course avatars", async () => {
    renderSidebar({ collapsed: true });

    expect(
      screen.getByRole("button", { name: "展开侧边栏" })
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "新对话" })
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "课程" })
    ).toBeTruthy();

    expect(screen.queryByText("Python 数据分析")).toBeNull();
    expect(screen.queryByText("P")).toBeNull();
  });

  it("has exactly one create-course action in the course list", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    // 新建课程只出现在课程列表视图（aria-label 新建课程）
    const addBtns = screen.getAllByRole("button", { name: "新建课程" });
    expect(addBtns.length).toBe(1);
  });

  it("mobile open shows backdrop", async () => {
    const { container } = renderSidebar({ open: true });
    await waitFor(() => expect(container.querySelector(".sidebar-backdrop")).toBeTruthy());
  });

  it("opens rename modal from more menu and updates sidebar state in place", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("重命名"));
    await waitFor(() => expect(screen.getByText("重命名课程")).toBeTruthy());
    const input = screen.getByLabelText("课程名") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Python 进阶" } });
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() =>
      expect((mockApi.renameCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        "Python 进阶"
      )
    );
    // 就地更新侧边栏状态（不重新拉取列表）
    await waitFor(() => expect(screen.getByText("Python 进阶")).toBeTruthy());
    // 根因修复验证：rename 只改本地 state，useApi 引用稳定，listCourses 仅初始化调用一次
    expect(mockApi.listCourses).toHaveBeenCalledTimes(1);
  });

  it("opens delete dialog and removes the course from sidebar on confirm", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("删除课程"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "删除课程" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除课程" }));
    await waitFor(() =>
      expect((mockApi.deleteCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("PY")
    );
    await waitFor(() => expect(screen.queryByText("Python 数据分析")).toBeNull());
    // 根因修复验证：delete 只改本地 state，useApi 引用稳定，listCourses 仅初始化调用一次
    expect(mockApi.listCourses).toHaveBeenCalledTimes(1);
  });
});
