import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AlertCircle, GraduationCap, PanelLeftClose, Plus } from "lucide-react";
import type { Course } from "../api/types";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";
import { useApi } from "../api/ApiProvider";
import "./sidebar.css";

/** SidebarLogo：展开显示 Logo + EduAgents；折叠只显示 Logo（本身可点击展开）。 */
export function SidebarLogo({ collapsed, onExpand }: { collapsed: boolean; onExpand?: () => void }) {
  return (
    <div className={`sidebar-logo ${collapsed ? "collapsed" : ""}`}>
      {collapsed ? (
        <button
          type="button"
          className="sidebar-logo-btn"
          onClick={onExpand}
          title="展开侧边栏"
          aria-label="展开侧边栏"
        >
          <span className="sidebar-logo-mark">
            <GraduationCap size={18} aria-hidden />
          </span>
        </button>
      ) : (
        <>
          <span className="sidebar-logo-mark">
            <GraduationCap size={18} aria-hidden />
          </span>
          <span className="sidebar-brand">EduAgents</span>
        </>
      )}
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
      className={`course-nav-item ${active ? "active" : ""} ${collapsed ? "collapsed" : ""}`}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={course.display_name}
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
 * collapsed = 68px 真 icon rail（条件渲染，无竖排文字、无被挤压文字）。
 */
export function Sidebar({ open, collapsed, onClose, onToggleCollapse, newChat, navigateToCourse }: SidebarProps) {
  const { pathname } = useLocation();
  const api = useApi();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);

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

  // useLocation 驱动 active（navigate 后立即刷新，无需 popstate listener）
  useEffect(() => {
    load();
  }, [api]);

  // Esc 关闭 mobile drawer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const isNewChatActive = !pathname.includes("/courses/");
  const courseActive = (courseId: string) => pathname.includes(`/courses/${courseId}/`);

  return (
    <>
      <aside className={`sidebar ${collapsed ? "collapsed" : ""} ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <SidebarLogo collapsed={collapsed} onExpand={onToggleCollapse} />
          {!collapsed && (
            <button
              className="sidebar-toggle"
              onClick={onToggleCollapse}
              title="收起侧边栏"
              aria-label="收起侧边栏"
            >
              <PanelLeftClose size={18} aria-hidden />
            </button>
          )}
        </div>

        <button
          type="button"
          className={`sidebar-new-chat ${isNewChatActive ? "active" : ""} ${collapsed ? "collapsed" : ""}`}
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
            <div className={`sidebar-skeleton ${collapsed ? "collapsed" : ""}`} aria-busy="true">
              {collapsed ? (
                <>
                  <div className="skeleton-avatar" />
                  <div className="skeleton-avatar" />
                  <div className="skeleton-avatar" />
                </>
              ) : (
                <>
                  <div className="sidebar-skeleton-row" />
                  <div className="sidebar-skeleton-row" />
                  <div className="sidebar-skeleton-row" />
                </>
              )}
            </div>
          )}
          {error && !loading && (
            <div className={`sidebar-error ${collapsed ? "collapsed" : ""}`} role="alert">
              {collapsed ? (
                <button
                  type="button"
                  className="sidebar-error-icon-btn"
                  onClick={load}
                  title="课程加载失败，点击重试"
                  aria-label="课程加载失败，点击重试"
                >
                  <AlertCircle size={18} aria-hidden />
                </button>
              ) : (
                <>
                  <div>课程加载失败</div>
                  <button className="ea-button" onClick={load}>
                    重试
                  </button>
                </>
              )}
            </div>
          )}
          {!loading && !error && courses.length === 0 && !collapsed && (
            <div className="course-empty">还没有课程</div>
          )}
          {courses.map((course) => (
            <CourseNavItem
              key={course.course_id}
              course={course}
              active={courseActive(course.course_id)}
              collapsed={collapsed}
              onClick={() => {
                onClose();
                navigateToCourse(course.course_id);
              }}
            />
          ))}
          {collapsed && !loading && !error && (
            <div className="course-add-collapsed">
              <button
                type="button"
                className="course-add-btn"
                onClick={() => setShowCreate(true)}
                title="新建课程"
                aria-label="新建课程"
              >
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
