import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

const courses = [
  { course_id: "PY", display_name: "Python 数据分析" },
  { course_id: "JAVA", display_name: "Java OOP" },
  { course_id: "TRANSFORMER", display_name: "Transformer" },
];

vi.mock("../api/client", () => ({
  api: {
    listCourses: vi.fn().mockResolvedValue(courses),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    createCourse: vi.fn(),
  },
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
});
