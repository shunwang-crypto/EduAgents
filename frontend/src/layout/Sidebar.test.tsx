import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

const { mockApi } = vi.hoisted(() => {
  const courses = [
    { course_id: "PY", display_name: "Python 数据分析", category_id: "CAT-PY", current_goal: "掌握 pandas" },
    { course_id: "JAVA", display_name: "Java OOP", category_id: "CAT-JAVA", current_goal: "掌握面向对象" },
    { course_id: "TRANSFORMER", display_name: "Transformer", category_id: null, current_goal: null },
  ];
  const categories = [
    { category_id: "CAT-PY", name: "Python" },
    { category_id: "CAT-JAVA", name: "Java" },
  ];
  const mockApi = {
    listCourses: vi.fn().mockResolvedValue(courses),
    listCourseCategories: vi.fn().mockResolvedValue(categories),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
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
      .mockResolvedValue({ course_id: "PY", display_name: "Python 进阶", category_id: "CAT-PY" }),
    deleteCourse: vi.fn().mockResolvedValue(undefined),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析", category_id: "CAT-PY" }),
  };
  return { mockApi };
});

// 返回严格同一个 object reference：Sidebar 的 useEffect([api]) 依赖 api 引用稳定性，
// 引用不变则 rerender 不触发 load()，rename/delete/move 的本地 state 更新不会被 fixture 重新加载覆盖。
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

/** 进入 Python 分类的课程列表（真实导航路径：课程 → 分类列表 → Python）。 */
async function openPythonCategory() {
  fireEvent.click(screen.getByRole("button", { name: "课程" }));
  await waitFor(() => expect(screen.getByText("Python")).toBeTruthy());
  fireEvent.click(screen.getByText("Python"));
  await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
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

  it("courses entry opens category list, then Python category shows its own courses", async () => {
    renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: "课程" }));

    // 分类列表：分类行 + 计数 + 未分类 pseudo-row，不直接展开所有课程
    await waitFor(() => expect(screen.getByText("课程分类")).toBeTruthy());
    expect(screen.getByText("Python")).toBeTruthy();
    expect(screen.getByText("Java")).toBeTruthy();
    expect(screen.getByText("未分类")).toBeTruthy();
    expect(screen.getByText("1 门课程")).toBeTruthy();
    // 分类列表不直接显示课程
    expect(screen.queryByText("Python 数据分析")).toBeNull();

    // 进入 Python 分类 → 只显示该分类课程
    fireEvent.click(screen.getByText("Python"));
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    expect(screen.queryByText("Java OOP")).toBeNull();
  });

  it("uncategorized pseudo-row shows only uncategorized courses", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("未分类")).toBeTruthy());
    fireEvent.click(screen.getByText("未分类"));
    await waitFor(() => expect(screen.getByText("Transformer")).toBeTruthy());
    expect(screen.queryByText("Python 数据分析")).toBeNull();
  });

  it("empty state (0 categories, 0 courses) still allows creating a course", async () => {
    mockApi.listCourses.mockResolvedValueOnce([]);
    mockApi.listCourseCategories.mockResolvedValueOnce([]);
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    // 空分类列表仍同时提供「新建课程」与「新建分类」
    await waitFor(() => expect(screen.getByText("还没有课程分类")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "新建课程" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "新建课程" })).toBeTruthy()
    );
    // 无分类上下文 → defaultCategoryId = null（未分类）
    const categorySelect = screen.getByLabelText("分类（可选）") as HTMLSelectElement;
    expect(categorySelect.value).toBe("");
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
    await openPythonCategory();
    const pyBtn = screen.getByText("Python 数据分析").closest("button");
    expect(pyBtn?.getAttribute("aria-current")).toBe("page");
    // Java 分类里没有 PY 课程
    expect(screen.queryByText("Java OOP")).toBeNull();
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

  it("category list has both create-course and create-category actions", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "课程" }));
    await waitFor(() => expect(screen.getByText("课程分类")).toBeTruthy());
    // 新建课程只出现在分类列表视图（aria-label 新建课程）
    const addBtns = screen.getAllByRole("button", { name: "新建课程" });
    expect(addBtns.length).toBe(1);
    expect(screen.getByRole("button", { name: "新建分类" })).toBeTruthy();
  });

  it("mobile open shows backdrop", async () => {
    const { container } = renderSidebar({ open: true });
    await waitFor(() => expect(container.querySelector(".sidebar-backdrop")).toBeTruthy());
  });

  it("opens rename modal from more menu and updates sidebar state in place", async () => {
    renderSidebar();
    await openPythonCategory();
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("重命名"));
    await waitFor(() => expect(screen.getByText("重命名课程")).toBeTruthy());
    const input = screen.getByLabelText("课程名") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Python 进阶" } });
    fireEvent.click(screen.getByText("保存"));
    // production contract：renameCourse(courseId, { display_name })（字段级 PATCH body）
    await waitFor(() =>
      expect((mockApi.renameCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        { display_name: "Python 进阶" }
      )
    );
    // 就地更新侧边栏状态（不重新拉取列表）
    await waitFor(() => expect(screen.getByText("Python 进阶")).toBeTruthy());
    // 根因修复验证：rename 只改本地 state，useApi 引用稳定，listCourses 仅初始化调用一次
    expect(mockApi.listCourses).toHaveBeenCalledTimes(1);
  });

  it("opens delete dialog and removes the course from sidebar on confirm", async () => {
    renderSidebar();
    await openPythonCategory();
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("删除课程"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "删除课程" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除课程" }));
    await waitFor(() =>
      expect((mockApi.deleteCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("PY")
    );
    await waitFor(() => expect(screen.queryByText("Python 数据分析")).toBeNull());
    expect(mockApi.listCourses).toHaveBeenCalledTimes(1);
  });

  it("moves course to another category via move-category modal", async () => {
    renderSidebar();
    await openPythonCategory();
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("移动到分类"));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "移动到分类" })).toBeTruthy()
    );
    // 选项来自用户自己的分类（不硬编码）：未分类 + Python + Java
    fireEvent.click(screen.getByText("Java"));
    await waitFor(() =>
      expect((mockApi.renameCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
        "PY",
        { category_id: "CAT-JAVA" }
      )
    );
    // 从 Python 分类列表立即消失（课程本身不删除）
    await waitFor(() => expect(screen.queryByText("Python 数据分析")).toBeNull());
    expect(mockApi.listCourses).toHaveBeenCalledTimes(1);
  });
});
