import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  GraduationCap,
  Library,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
} from "lucide-react";
import type { ConversationSummary, Course } from "../api/types";
import { subscribeConversationUpdated } from "../api/conversationEvents";
import { openCourseSources } from "../features/course/courseSourcesEvents";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";
import { RenameCourseModal } from "../features/courses/RenameCourseModal";
import { DeleteCourseDialog } from "../features/courses/DeleteCourseDialog";
import { useApi } from "../api/ApiProvider";
import { useLearningNav } from "../app/useLearningNav";
import "./sidebar.css";

type SidebarView =
  | { kind: "root" }
  | { kind: "courseList" }
  | { kind: "workspace"; courseId: string };

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

/** CourseNavItem：展开显示 avatar + 课程名 + 更多按钮。
 * 结构：.course-nav-row 内两个 sibling 按钮（.course-nav-main 导航 / .course-nav-more 打开菜单），
 * 不嵌套 button（避免无效 HTML / a11y 问题）。 */
export function CourseNavItem({
  course,
  active,
  collapsed,
  onOpen,
  onToggleMenu,
  menuOpen,
  onRename,
  onDelete,
}: {
  course: Course;
  active: boolean;
  collapsed: boolean;
  onOpen: () => void;
  onToggleMenu: () => void;
  menuOpen: boolean;
  onRename: () => void;
  onDelete: () => void;
}) {
  const avatar = course.display_name?.trim().charAt(0) || "?";
  return (
    <div className={`course-nav-row ${active ? "active" : ""} ${collapsed ? "collapsed" : ""}`}>
      <button
        type="button"
        className={`course-nav-main ${collapsed ? "collapsed" : ""}`}
        onClick={onOpen}
        aria-current={active ? "page" : undefined}
        title={course.display_name}
      >
        <span className="course-avatar" aria-hidden>
          {avatar}
        </span>
        {!collapsed && <span className="course-name">{course.display_name}</span>}
      </button>
      {!collapsed && (
        <button
          type="button"
          className="course-nav-more"
          onClick={onToggleMenu}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`更多操作：${course.display_name}`}
          title="更多操作"
        >
          <MoreHorizontal size={16} aria-hidden />
        </button>
      )}
      {!collapsed && menuOpen && (
        <div className="course-nav-menu" role="menu">
          <button type="button" className="course-nav-menu-item" role="menuitem" onClick={onRename}>
            重命名
          </button>
          <button
            type="button"
            className="course-nav-menu-item danger"
            role="menuitem"
            onClick={onDelete}
          >
            删除课程
          </button>
        </div>
      )}
    </div>
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

/** Sidebar：三视图（Root / Course List / Course Workspace）+ GPT 式「最近对话」。
 * collapsed = 68px 真 icon rail（条件渲染，无竖排文字、无被挤压文字）。
 */
export function Sidebar({
  open,
  collapsed,
  onClose,
  onToggleCollapse,
  newChat,
  navigateToCourse,
}: SidebarProps) {
  const { pathname } = useLocation();
  const api = useApi();
  const nav = useLearningNav();

  // 课程列表
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 最近对话（当前视图作用域：general 或某 course）
  const [recent, setRecent] = useState<ConversationSummary[]>([]);
  const [recentLoading, setRecentLoading] = useState(false);
  const [recentError, setRecentError] = useState("");
  const [expandedRecent, setExpandedRecent] = useState(false);
  // 课程菜单 / 重命名 / 删除 状态
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Course | null>(null);
  const [deleting, setDeleting] = useState<Course | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // 三视图：course 路由 → workspace；否则保留 courseList 手动态，否则 root
  const [view, setView] = useState<SidebarView>({ kind: "root" });

  // stale-async 保护
  const courseSeq = useRef(0);
  const recentSeq = useRef(0);
  // 订阅闭包读取最新 view / expandedRecent（不重订阅）
  const viewRef = useRef(view);
  viewRef.current = view;
  const expandedRecentRef = useRef(expandedRecent);
  expandedRecentRef.current = expandedRecent;

  const loadCourses = () => {
    const seq = ++courseSeq.current;
    setLoading(true);
    setError("");
    api
      .listCourses()
      .then((list) => {
        if (seq !== courseSeq.current) return;
        setCourses(list);
        setLoading(false);
      })
      .catch((e) => {
        if (seq !== courseSeq.current) return;
        setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      });
  };

  const loadRecent = (courseId: string | null, limit: number) => {
    const seq = ++recentSeq.current;
    setRecentLoading(true);
    setRecentError("");
    api
      .listConversations(courseId, limit)
      .then((list) => {
        if (seq !== recentSeq.current) return;
        setRecent(list);
        setRecentLoading(false);
      })
      .catch((e) => {
        if (seq !== recentSeq.current) return;
        setRecentError(e instanceof Error ? e.message : "加载失败");
        setRecentLoading(false);
      });
  };

  // 视图随路由：进入课程路由 → workspace；离开课程 → 保留 courseList 手动态或回 root
  useEffect(() => {
    const m = pathname.match(/\/courses\/([^/]+)\//);
    if (m) {
      setView({ kind: "workspace", courseId: m[1] });
    } else {
      setView((v) => (v.kind === "courseList" ? v : { kind: "root" }));
    }
  }, [pathname]);

  // 课程列表加载（api 稳定，仅首次 + 重命名/删除后）
  useEffect(() => {
    loadCourses();
  }, [api]);

  // 最近对话：随视图 / 展开态变化重新加载（stale guard 在 loadRecent 内）
  useEffect(() => {
    if (view.kind === "courseList") {
      setRecent([]);
      setExpandedRecent(false);
      return;
    }
    const courseId = view.kind === "workspace" ? view.courseId : null;
    const limit = view.kind === "workspace" ? 6 : expandedRecent ? 20 : 6;
    loadRecent(courseId, limit);
  }, [view, expandedRecent, api]);

  // 订阅对话更新事件：刷新当前作用域的最近对话（ChatPage 发消息后）
  useEffect(() => {
    return subscribeConversationUpdated(() => {
      const v = viewRef.current;
      if (v.kind === "courseList") return;
      const courseId = v.kind === "workspace" ? v.courseId : null;
      const limit = v.kind === "workspace" ? 6 : expandedRecentRef.current ? 20 : 6;
      loadRecent(courseId, limit);
    });
  }, [api]);

  // 菜单打开时，点击课程行外部关闭
  useEffect(() => {
    if (!menuOpenFor) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && !target.closest(".course-nav-row")) {
        setMenuOpenFor(null);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [menuOpenFor]);

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
  const workspaceCourseId = view.kind === "workspace" ? view.courseId : null;
  const workspaceCourse = courses.find((c) => c.course_id === workspaceCourseId) ?? null;

  const newCourseChat = async (courseId: string) => {
    try {
      const conv = await api.createConversation(courseId);
      nav.openCourseChat(courseId, { conversationId: conv.conversation_id });
    } catch {
      // 失败保持现状
    }
  };

  // 折叠：仅 68px icon rail（新对话 + 课程头像）
  if (collapsed) {
    return (
      <>
        <aside className="sidebar collapsed open">
          <div className="sidebar-header">
            <SidebarLogo collapsed onExpand={onToggleCollapse} />
          </div>
          <button
            type="button"
            className="sidebar-new-chat collapsed"
            onClick={() => {
              onClose();
              newChat();
            }}
            title="新对话"
            aria-label="新对话"
          >
            <Plus size={18} aria-hidden />
          </button>
          <div className="course-scroll-area">
            {!loading &&
              !error &&
              courses.map((course) => (
                <button
                  key={course.course_id}
                  type="button"
                  className={`course-avatar-collapsed ${courseActive(course.course_id) ? "active" : ""}`}
                  onClick={() => {
                    onClose();
                    navigateToCourse(course.course_id);
                  }}
                  title={course.display_name}
                  aria-label={course.display_name}
                >
                  {course.display_name?.trim().charAt(0) || "?"}
                </button>
              ))}
            <button
              type="button"
              className="course-add-btn collapsed"
              onClick={() => setShowCreate(true)}
              title="新建课程"
              aria-label="新建课程"
            >
              <Plus size={18} aria-hidden />
            </button>
          </div>
        </aside>
        {showCreate && (
          <CreateCourseModal
            onClose={() => setShowCreate(false)}
            onCreated={(course) => {
              setShowCreate(false);
              loadCourses();
              onClose();
              navigateToCourse(course.course_id);
            }}
          />
        )}
      </>
    );
  }

  return (
    <>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <SidebarLogo collapsed={false} onExpand={onToggleCollapse} />
          <button
            className="sidebar-toggle"
            onClick={onToggleCollapse}
            title="收起侧边栏"
            aria-label="收起侧边栏"
          >
            <PanelLeftClose size={18} aria-hidden />
          </button>
        </div>

        {/* Root：新对话 + 最近对话 + 我的课程 */}
        {view.kind === "root" && (
          <>
            <button
              type="button"
              className={`sidebar-new-chat ${isNewChatActive ? "active" : ""}`}
              onClick={() => {
                onClose();
                newChat();
              }}
            >
              <Plus size={18} aria-hidden />
              <span>新对话</span>
            </button>

            <div className="sidebar-section recent-section">
              <div className="sidebar-section-header">
                <span className="sidebar-section-title">
                  <MessageSquare size={14} aria-hidden /> 最近对话
                </span>
              </div>
              {recentLoading && <div className="sidebar-hint">加载中…</div>}
              {recentError && !recentLoading && <div className="sidebar-error-inline">{recentError}</div>}
              {!recentLoading && !recentError && recent.length === 0 && (
                <div className="sidebar-hint">暂无对话</div>
              )}
              {recent.map((conv) => (
                <button
                  key={conv.conversation_id}
                  type="button"
                  className="recent-item"
                  onClick={() => {
                    onClose();
                    nav.openGeneralChat(conv.conversation_id);
                  }}
                  title={conv.title}
                >
                  <MessageSquare size={14} aria-hidden />
                  <span className="recent-title">{conv.title || "未命名对话"}</span>
                </button>
              ))}
              {!recentLoading &&
                !recentError &&
                recent.length >= 6 &&
                !expandedRecent && (
                  <button
                    type="button"
                    className="sidebar-link-btn"
                    onClick={() => setExpandedRecent(true)}
                  >
                    更多
                  </button>
                )}
              {!recentLoading && !recentError && expandedRecent && (
                <button
                  type="button"
                  className="sidebar-link-btn"
                  onClick={() => setExpandedRecent(false)}
                >
                  收起
                </button>
              )}
            </div>

            <div className="course-section-header">
              <span className="course-section-title">我的课程</span>
              <button
                className="course-add-btn"
                onClick={() => setShowCreate(true)}
                title="新建课程"
                aria-label="新建课程"
              >
                <Plus size={16} aria-hidden />
              </button>
            </div>
            <div className="course-scroll-area">
              {loading && <div className="sidebar-hint">加载中…</div>}
              {error && !loading && <div className="sidebar-error-inline">{error}</div>}
              {!loading &&
                !error &&
                courses.length === 0 && <div className="course-empty">还没有课程</div>}
              {courses.slice(0, 5).map((course) => (
                <CourseNavItem
                  key={course.course_id}
                  course={course}
                  active={courseActive(course.course_id)}
                  collapsed={false}
                  onOpen={() => {
                    setMenuOpenFor(null);
                    onClose();
                    navigateToCourse(course.course_id);
                  }}
                  onToggleMenu={() =>
                    setMenuOpenFor((prev) => (prev === course.course_id ? null : course.course_id))
                  }
                  menuOpen={menuOpenFor === course.course_id}
                  onRename={() => {
                    setRenaming(course);
                    setMenuOpenFor(null);
                  }}
                  onDelete={() => {
                    setDeleting(course);
                    setMenuOpenFor(null);
                  }}
                />
              ))}
              {!loading && !error && courses.length > 5 && (
                <button
                  type="button"
                  className="sidebar-link-btn"
                  onClick={() => setView({ kind: "courseList" })}
                >
                  查看全部课程（{courses.length}）
                </button>
              )}
            </div>
          </>
        )}

        {/* Course List：全部课程 */}
        {view.kind === "courseList" && (
          <>
            <button
              type="button"
              className="sidebar-back-btn"
              onClick={() => setView({ kind: "root" })}
            >
              <ArrowLeft size={16} aria-hidden /> 返回
            </button>
            <div className="course-section-header">
              <span className="course-section-title">我的课程（{courses.length}）</span>
            </div>
            <div className="course-scroll-area">
              {loading && <div className="sidebar-hint">加载中…</div>}
              {error && !loading && <div className="sidebar-error-inline">{error}</div>}
              {!loading &&
                !error &&
                courses.length === 0 && <div className="course-empty">还没有课程</div>}
              {courses.map((course) => (
                <CourseNavItem
                  key={course.course_id}
                  course={course}
                  active={courseActive(course.course_id)}
                  collapsed={false}
                  onOpen={() => {
                    setMenuOpenFor(null);
                    onClose();
                    navigateToCourse(course.course_id);
                  }}
                  onToggleMenu={() =>
                    setMenuOpenFor((prev) => (prev === course.course_id ? null : course.course_id))
                  }
                  menuOpen={menuOpenFor === course.course_id}
                  onRename={() => {
                    setRenaming(course);
                    setMenuOpenFor(null);
                  }}
                  onDelete={() => {
                    setDeleting(course);
                    setMenuOpenFor(null);
                  }}
                />
              ))}
            </div>
          </>
        )}

        {/* Course Workspace：某课程的操作 + 最近对话 */}
        {view.kind === "workspace" && (
          <>
            <button
              type="button"
              className="sidebar-back-btn"
              onClick={() => {
                onClose();
                nav.openGeneralChat();
              }}
            >
              <ArrowLeft size={16} aria-hidden /> 返回
            </button>
            <div className="workspace-course-title">{workspaceCourse?.display_name ?? "课程"}</div>
            <div className="workspace-actions">
              <button
                type="button"
                className="workspace-action"
                onClick={() => {
                  onClose();
                  newCourseChat(workspaceCourseId!);
                }}
              >
                <Plus size={15} aria-hidden /> 新建课程对话
              </button>
              <button
                type="button"
                className="workspace-action"
                onClick={() => {
                  onClose();
                  nav.openCoursePlan(workspaceCourseId!);
                }}
              >
                <BookOpen size={15} aria-hidden /> 学习计划
              </button>
              <button
                type="button"
                className="workspace-action"
                onClick={() => {
                  onClose();
                  openCourseSources(workspaceCourseId!);
                }}
              >
                <Library size={15} aria-hidden /> 课程资料
              </button>
            </div>

            <div className="sidebar-section recent-section">
              <div className="sidebar-section-header">
                <span className="sidebar-section-title">
                  <MessageSquare size={14} aria-hidden /> 最近对话
                </span>
              </div>
              {recentLoading && <div className="sidebar-hint">加载中…</div>}
              {recentError && !recentLoading && <div className="sidebar-error-inline">{recentError}</div>}
              {!recentLoading && !recentError && recent.length === 0 && (
                <div className="sidebar-hint">该课程暂无对话</div>
              )}
              {recent.map((conv) => (
                <button
                  key={conv.conversation_id}
                  type="button"
                  className="recent-item"
                  onClick={() => {
                    onClose();
                    nav.openCourseChat(workspaceCourseId!, { conversationId: conv.conversation_id });
                  }}
                  title={conv.title}
                >
                  <MessageSquare size={14} aria-hidden />
                  <span className="recent-title">{conv.title || "未命名对话"}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </aside>

      {open && <div className="sidebar-backdrop" onClick={onClose} aria-label="关闭侧边栏" />}

      {showCreate && (
        <CreateCourseModal
          onClose={() => setShowCreate(false)}
          onCreated={(course) => {
            setShowCreate(false);
            loadCourses();
            onClose();
            navigateToCourse(course.course_id);
          }}
        />
      )}

      {renaming && (
        <RenameCourseModal
          course={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={(id, name) => {
            setCourses((prev) => prev.map((c) => (c.course_id === id ? { ...c, display_name: name } : c)));
            setRenaming(null);
          }}
        />
      )}

      {deleting && (
        <DeleteCourseDialog
          course={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={(id) => {
            setCourses((prev) => prev.filter((c) => c.course_id !== id));
            setDeleting(null);
            if (courseActive(id)) {
              nav.openGeneralChat();
            }
          }}
        />
      )}
    </>
  );
}
