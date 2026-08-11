import { Menu } from "lucide-react";
import type { Course } from "../api/types";
import { useLearningNav } from "../app/useLearningNav";

interface CourseHeaderProps {
  course: Course | null;
  activeView: "chat" | "plan" | "general";
  onOpenMobileSidebar: () => void;
}

/** CourseHeader：移动端菜单 + 标题 + 对话/学习计划 tab（统一，不重复实现）。 */
export function CourseHeader({ course, activeView, onOpenMobileSidebar }: CourseHeaderProps) {
  const nav = useLearningNav();
  const showTabs = Boolean(course);

  const title = course ? course.display_name : "新对话";

  return (
    <header className="course-header">
      <button type="button" className="header-menu-btn" onClick={onOpenMobileSidebar} aria-label="打开菜单">
        <Menu size={20} aria-hidden />
      </button>
      <h1 className="header-title" title={title}>
        {title}
      </h1>
      {showTabs && (
        <nav className="header-tabs" aria-label="视图切换">
          <button
            type="button"
            className={`header-tab ${activeView === "chat" ? "active" : ""}`}
            onClick={() => nav.openCourseChat(course!.course_id)}
          >
            对话
          </button>
          <button
            type="button"
            className={`header-tab ${activeView === "plan" ? "active" : ""}`}
            onClick={() => nav.openCoursePlan(course!.course_id)}
          >
            学习计划
          </button>
        </nav>
      )}
    </header>
  );
}
