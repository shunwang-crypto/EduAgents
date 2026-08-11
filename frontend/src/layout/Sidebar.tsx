import { useEffect, useState } from "react";
import { GraduationCap, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import type { Course } from "../api/types";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";
import { api } from "../api/client";

/** SidebarLogo：展开显示 Logo + EduAgents；折叠只显示 Logo。 */
export function SidebarLogo({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="sidebar-logo">
      <span className="sidebar-logo-mark" title="EduAgents">
        <GraduationCap size={18} aria-hidden />
      </span>
      {!collapsed && <span className="sidebar-brand">EduAgents</span>}
    </div>
  );
}

/** CourseNavItem：展开显示 avatar + 课程名；折叠只显示 avatar（首字符）。 */
export function CourseNavItem({
  course,
  active,
  collapsed,
  onClick,
}: {
  course: Course;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
}) {
  const avatar = course.display_name?.trim().charAt(0) || "?";
  return (
    <button
      type="button"
      className={`course-nav-item ${active ? "active" : ""}`}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={course.display_name}
      style={collapsed ? { justifyContent: "center", padding: "8px 0" } : undefined}
    >
      <span className="course-avatar" aria-hidden>
        {avatar}
      </span>
      {!collapsed && <span className="course-name">{course.display_name}</span>}
    </button>
  );
}

interface SidebarProps {
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  onToggleCollapse: () => void;
  newChat: () => void;
  navigateToCourse: (courseId: string) => void;
}

/** Sidebar：EduAgents + 新对话 + 我的课程（唯一新建入口）。
 * collapsed = 68px 真 icon rail（条件渲染，无竖排文字）。 */
export function Sidebar({ open, collapsed, onClose, onToggleCollapse, newChat, navigateToCourse }: SidebarProps) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [path, setPath] = useState(typeof window !== "undefined" ? window.location.pathname : "/");

  const load = () => {
    setLoading(true);
    setError("");
    api
      .listCourses()
      .then((list) => {
        setCourses(list);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Esc 关闭 mobile drawer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const isNewChatActive = !path.includes("/courses/");

  return (
    <>
      <aside className={`sidebar ${collapsed ? "collapsed" : ""} ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <SidebarLogo collapsed={collapsed} />
          <button
            className="sidebar-toggle"
            onClick={onToggleCollapse}
            title={collapsed ? "展开" : "收起"}
            aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
          </button>
        </div>

        <button
          type="button"
          className={`sidebar-new-chat ${isNewChatActive ? "active" : ""}`}
          onClick={() => {
            onClose();
            newChat();
          }}
          title={collapsed ? "新对话" : undefined}
          aria-label={collapsed ? "新对话" : undefined}
        >
          <Plus size={18} aria-hidden />
          {!collapsed && <span>新对话</span>}
        </button>

        {!collapsed && (
          <div className="course-section-header">
            <span className="course-section-title">我的课程</span>
            <button className="course-add-btn" onClick={() => setShowCreate(true)} title="新建课程" aria-label="新建课程">
              <Plus size={16} aria-hidden />
            </button>
          </div>
        )}

        <div className="course-scroll-area">
          {loading && (
            <div className="sidebar-skeleton" aria-busy="true">
              <div className="sidebar-skeleton-row" />
              <div className="sidebar-skeleton-row" />
              <div className="sidebar-skeleton-row" />
            </div>
          )}
          {error && !loading && (
            <div className="sidebar-error" role="alert">
              <div>课程加载失败</div>
              <button className="btn" onClick={load}>
                重试
              </button>
            </div>
          )}
          {!loading && !error && courses.length === 0 && !collapsed && (
            <div className="course-empty">还没有课程</div>
          )}
          {courses.map((course) => (
            <CourseNavItem
              key={course.course_id}
              course={course}
              active={path.includes(`/courses/${course.course_id}/`)}
              collapsed={collapsed}
              onClick={() => {
                onClose();
                navigateToCourse(course.course_id);
              }}
            />
          ))}
          {collapsed && !loading && !error && (
            <div style={{ padding: "6px 0", display: "flex", justifyContent: "center" }}>
              <button className="course-add-btn" onClick={() => setShowCreate(true)} title="新建课程" aria-label="新建课程">
                <Plus size={18} aria-hidden />
              </button>
            </div>
          )}
        </div>
      </aside>

      {open && <div className="sidebar-backdrop" onClick={onClose} aria-label="关闭侧边栏" />}

      {showCreate && (
        <CreateCourseModal
          onClose={() => setShowCreate(false)}
          onCreated={(course) => {
            setShowCreate(false);
            load();
            onClose();
            navigateToCourse(course.course_id);
          }}
        />
      )}
    </>
  );
}
