import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

const { courses, mockApi } = vi.hoisted(() => ({
  courses: [
    { course_id: "PY", display_name: "Python 数据分析" },
    { course_id: "JAVA", display_name: "Java OOP" },
    { course_id: "TRANSFORMER", display_name: "Transformer" },
  ],
  mockApi: {
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    createCourse: vi.fn(),
    renameCourse: vi
      .fn()
      .mockResolvedValue({ course_id: "PY", display_name: "Python 进阶" }),
    deleteCourse: vi.fn().mockResolvedValue(undefined),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python 数据分析" }),
  },
}));

vi.mock("../api/ApiProvider", () => ({
  useApi: () => ({
    ...mockApi,
    listCourses: vi.fn().mockResolvedValue(courses),
  }),
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
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    const pyBtn = screen.getByText("Python 数据分析").closest("button");
    expect(pyBtn?.getAttribute("aria-current")).toBe("page");
    const javaBtn = screen.getByText("Java OOP").closest("button");
    expect(javaBtn?.getAttribute("aria-current")).toBeNull();
  });

  it("collapsed header shows single logo control (no dual toggle)", async () => {
    renderSidebar({ collapsed: true });
    await waitFor(() => expect(screen.getAllByText("P").length).toBeGreaterThan(0));
    // 折叠态只有一个「展开侧边栏」Logo 按钮，没有收起按钮
    expect(screen.getByRole("button", { name: "展开侧边栏" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "收起侧边栏" })).toBeNull();
  });

  it("expanded shows brand, 我的课程, and full course names", async () => {
    renderSidebar();
    await waitFor(() => expect(screen.getByText("EduAgents")).toBeTruthy());
    expect(screen.getByText("我的课程")).toBeTruthy();
    expect(screen.getByText("Python 数据分析")).toBeTruthy();
    expect(screen.getByText("Java OOP")).toBeTruthy();
  });

  it("collapsed hides text labels, shows only avatars (no vertical text)", async () => {
    renderSidebar({ collapsed: true });
    await waitFor(() => expect(screen.getAllByText("P").length).toBeGreaterThan(0));
    // 文字标签不参与布局
    expect(screen.queryByText("EduAgents")).toBeNull();
    expect(screen.queryByText("我的课程")).toBeNull();
    expect(screen.queryByText("Python 数据分析")).toBeNull();
    expect(screen.queryByText("新对话")).toBeNull();
    // avatar 首字符
    expect(screen.getByText("P")).toBeTruthy();
    expect(screen.getByText("J")).toBeTruthy();
  });

  it("has exactly one create-course action in expanded mode", async () => {
    renderSidebar();
    await waitFor(() => expect(screen.getByText("我的课程")).toBeTruthy());
    // 顶部 section + 按钮只有 1 个业务入口（aria-label 新建课程）
    const addBtns = screen.getAllByRole("button", { name: "新建课程" });
    expect(addBtns.length).toBe(1);
  });

  it("mobile open shows backdrop", async () => {
    const { container } = renderSidebar({ open: true });
    await waitFor(() => expect(container.querySelector(".sidebar-backdrop")).toBeTruthy());
  });

  it("opens rename modal from more menu and updates sidebar state in place", async () => {
    renderSidebar();
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
  });

  it("opens delete dialog and removes the course from sidebar on confirm", async () => {
    renderSidebar();
    await waitFor(() => expect(screen.getByText("Python 数据分析")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "更多操作：Python 数据分析" }));
    fireEvent.click(screen.getByText("删除课程"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "删除课程" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除课程" }));
    await waitFor(() =>
      expect((mockApi.deleteCourse as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("PY")
    );
    await waitFor(() => expect(screen.queryByText("Python 数据分析")).toBeNull());
  });
});
