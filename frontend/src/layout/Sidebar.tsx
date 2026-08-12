import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  GraduationCap,
  Library,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
} from "lucide-react";
import type { ConversationSummary, Course, CourseCategory } from "../api/types";
import { subscribeConversationUpdated } from "../api/conversationEvents";
import { openCourseSources } from "../features/course/courseSourcesEvents";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";
import { RenameCourseModal } from "../features/courses/RenameCourseModal";
import { DeleteCourseDialog } from "../features/courses/DeleteCourseDialog";
import { useApi } from "../api/ApiProvider";
import { useLearningNav } from "../app/useLearningNav";
import "./sidebar.css";
// 分类新建/重命名/删除对话框复用课程 modal 基础样式（backdrop/modal/title/label/actions）
import "../features/courses/courses.css";

type SidebarView =
  | { kind: "root" }
  | { kind: "categoryList" }
  | { kind: "categoryCourses"; categoryId: string | null }
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

/** 分类名称对话框（新建 / 重命名共用）：预填、Esc 关闭、提交后由 onSubmit 负责关闭。 */
function CategoryNameModal({
  title,
  label,
  initial,
  confirmLabel,
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  initial: string;
  confirmLabel: string;
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, loading]);

  const submit = async () => {
    const next = name.trim();
    if (!next) {
      setError("分类名称不能为空");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await onSubmit(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => !loading && onClose()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="category-name-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="category-name-title" className="modal-title">
          {title}
        </h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="modal-label" htmlFor="category-name-input">
            {label}
          </label>
          <input
            id="category-name-input"
            ref={inputRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：Python"
            autoComplete="off"
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="ea-button" onClick={onClose} disabled={loading}>
              取消
            </button>
            <button type="submit" className="ea-button primary" disabled={loading}>
              {loading ? "保存中…" : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** 删除分类确认对话框：课程不会被删除，只会移动到「未分类」。 */
function DeleteCategoryDialog({
  category,
  onClose,
  onDeleted,
}: {
  category: CourseCategory;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const api = useApi();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const confirm = async () => {
    setLoading(true);
    setError("");
    try {
      await api.deleteCourseCategory(category.category_id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败，请重试");
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => !loading && onClose()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-category-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="delete-category-title" className="modal-title">
          删除分类
        </h3>
        <p className="modal-text">
          删除分类“{category.name}”？分类中的课程不会被删除，它们会移动到“未分类”。
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="ea-button" onClick={onClose} disabled={loading}>
            取消
          </button>
          <button
            type="button"
            className="ea-button danger"
            onClick={() => void confirm()}
            disabled={loading}
          >
            {loading ? "删除中…" : "删除分类"}
          </button>
        </div>
      </div>
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
  // 课程分类（纯组织层：把用户自己创建的课程分组；零 Adaptive 语义）
  const [categories, setCategories] = useState<CourseCategory[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoriesError, setCategoriesError] = useState("");
  // 分类创建 / 重命名 / 删除对话框
  const [showCreateCategory, setShowCreateCategory] = useState(false);
  const [renamingCategory, setRenamingCategory] = useState<CourseCategory | null>(null);
  const [deletingCategory, setDeletingCategory] = useState<CourseCategory | null>(null);
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

  // 视图：course 路由 → workspace；否则保留分类视图手动态，否则 root
  const [view, setView] = useState<SidebarView>({ kind: "root" });

  // stale-async 保护
  const courseSeq = useRef(0);
  const recentSeq = useRef(0);
  const categorySeq = useRef(0);
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

  const loadCategories = () => {
    const seq = ++categorySeq.current;
    setCategoriesLoading(true);
    setCategoriesError("");
    api
      .listCourseCategories()
      .then((list) => {
        if (seq !== categorySeq.current) return;
        setCategories(list);
        setCategoriesLoading(false);
      })
      .catch((e) => {
        if (seq !== categorySeq.current) return;
        setCategoriesError(e instanceof Error ? e.message : "加载失败");
        setCategoriesLoading(false);
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
        console.error("Failed to load conversations", e);
        setRecentError("无法加载最近对话");
        setRecentLoading(false);
      });
  };

  // 视图随路由：进入课程路由 → workspace；离开课程 → 保留分类视图手动态或回 root
  useEffect(() => {
    const m = pathname.match(/\/courses\/([^/]+)\//);
    if (m) {
      setView({ kind: "workspace", courseId: m[1] });
    } else {
      setView((v) =>
        v.kind === "categoryList" || v.kind === "categoryCourses" ? v : { kind: "root" }
      );
    }
  }, [pathname]);

  // 课程 + 分类加载（api 稳定，仅首次 + 重命名/删除后）
  useEffect(() => {
    loadCourses();
    loadCategories();
  }, [api]);

  // 最近对话：随视图 / 展开态变化重新加载（stale guard 在 loadRecent 内）
  useEffect(() => {
    if (view.kind === "categoryList" || view.kind === "categoryCourses") {
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
      if (v.kind === "categoryList" || v.kind === "categoryCourses") return;
      const courseId = v.kind === "workspace" ? v.courseId : null;
      const limit = v.kind === "workspace" ? 6 : expandedRecentRef.current ? 20 : 6;
      loadRecent(courseId, limit);
    });
  }, [api]);

  // 菜单打开时，点击课程行/分类行外部关闭
  useEffect(() => {
    if (!menuOpenFor) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && !target.closest(".course-nav-row") && !target.closest(".category-row")) {
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
          <div className="sidebar-rail-actions">
            <button
              type="button"
              className="sidebar-rail-action"
              onClick={() => {
                setView({ kind: "categoryList" });
                onToggleCollapse();
              }}
              title="课程"
              aria-label="课程"
            >
              <Library size={18} aria-hidden />
            </button>
          </div>
        </aside>
        {showCreate && (
          <CreateCourseModal
            defaultCategoryId={view.kind === "categoryCourses" ? view.categoryId : null}
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

            <button
              type="button"
              className="sidebar-nav-action"
              onClick={() => {
                setView({ kind: "categoryList" });
              }}
            >
              <Library size={18} aria-hidden />
              <span>课程</span>
            </button>

            <div className="sidebar-section recent-section">
              <div className="sidebar-section-header">
                <span className="sidebar-section-title">最近</span>
              </div>

              {recentLoading && (
                <div className="sidebar-hint">加载中…</div>
              )}

              {recentError && !recentLoading && (
                <div className="sidebar-error-inline">
                  <span>无法加载最近对话</span>
                  <button
                    type="button"
                    className="sidebar-retry-btn"
                    onClick={() =>
                      loadRecent(null, expandedRecent ? 20 : 6)
                    }
                  >
                    重试
                  </button>
                </div>
              )}

              {!recentLoading &&
                !recentError &&
                recent.length === 0 && (
                  <div className="sidebar-hint">
                    暂无最近对话
                  </div>
                )}

              {recent.map((conv) => (
                <button
                  key={conv.conversation_id}
                  type="button"
                  className="recent-item"
                  title={conv.title}
                  onClick={() => {
                    onClose();
                    nav.openGeneralChat(conv.conversation_id);
                  }}
                >
                  <span className="recent-title">
                    {conv.title || "未命名对话"}
                  </span>
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

              {expandedRecent && (
                <button
                  type="button"
                  className="sidebar-link-btn"
                  onClick={() => setExpandedRecent(false)}
                >
                  收起
                </button>
              )}
            </div>
          </>
        )}

        {/* Course List：默认显示 5 门 */}
        {/* 分类列表：课程导航入口（Category = 用户自己创建的课程分组，纯组织层） */}
        {view.kind === "categoryList" && (
          <>
            <button
              type="button"
              className="sidebar-back-btn"
              onClick={() => setView({ kind: "root" })}
            >
              <ArrowLeft size={16} aria-hidden />
              <span>返回</span>
            </button>

            <button
              type="button"
              className="sidebar-nav-action"
              onClick={() => setShowCreateCategory(true)}
            >
              <Plus size={18} aria-hidden />
              <span>新建分类</span>
            </button>

            <div className="sidebar-section-header">
              <span className="sidebar-section-title">课程分类</span>
            </div>

            <div className="course-scroll-area">
              {categoriesLoading && <div className="sidebar-hint">加载中…</div>}
              {categoriesError && !categoriesLoading && (
                <div className="sidebar-error-inline">无法加载分类</div>
              )}
              {!categoriesLoading &&
                !categoriesError &&
                categories.length === 0 &&
                courses.length === 0 && <div className="course-empty">还没有课程，先创建一门吧</div>}
              {categories.map((cat) => {
                const count = courses.filter((c) => c.category_id === cat.category_id).length;
                const menuOpen = menuOpenFor === `cat:${cat.category_id}`;
                return (
                  <div key={cat.category_id} className="category-row">
                    <button
                      type="button"
                      className="category-row-main"
                      onClick={() => {
                        setMenuOpenFor(null);
                        setView({ kind: "categoryCourses", categoryId: cat.category_id });
                      }}
                      title={cat.name}
                    >
                      <span className="category-name">{cat.name}</span>
                      <span className="category-count">{count} 门课程</span>
                    </button>
                    <button
                      type="button"
                      className="course-nav-more"
                      onClick={() =>
                        setMenuOpenFor(menuOpen ? null : `cat:${cat.category_id}`)
                      }
                      aria-haspopup="menu"
                      aria-expanded={menuOpen}
                      aria-label={`更多操作：${cat.name}`}
                      title="更多操作"
                    >
                      <MoreHorizontal size={16} aria-hidden />
                    </button>
                    {menuOpen && (
                      <div className="course-nav-menu" role="menu">
                        <button
                          type="button"
                          className="course-nav-menu-item"
                          role="menuitem"
                          onClick={() => {
                            setRenamingCategory(cat);
                            setMenuOpenFor(null);
                          }}
                        >
                          重命名分类
                        </button>
                        <button
                          type="button"
                          className="course-nav-menu-item danger"
                          role="menuitem"
                          onClick={() => {
                            setDeletingCategory(cat);
                            setMenuOpenFor(null);
                          }}
                        >
                          删除分类
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
              {/* 未分类是前端 pseudo-category（category_id=null），仅当存在未分类课程时显示 */}
              {!categoriesLoading &&
                !categoriesError &&
                courses.some((c) => !c.category_id) && (
                  <button
                    type="button"
                    className="category-row-main uncategorized-row"
                    onClick={() => setView({ kind: "categoryCourses", categoryId: null })}
                    title="未分类"
                  >
                    <span className="category-name">未分类</span>
                    <span className="category-count">
                      {courses.filter((c) => !c.category_id).length} 门课程
                    </span>
                  </button>
                )}
            </div>
          </>
        )}

        {/* 分类内课程：只显示 category_id == 当前分类（null = 未分类）的课程 */}
        {view.kind === "categoryCourses" && (
          <>
            <button
              type="button"
              className="sidebar-back-btn"
              onClick={() => setView({ kind: "categoryList" })}
            >
              <ArrowLeft size={16} aria-hidden />
              <span>所有分类</span>
            </button>

            <div className="workspace-course-title">
              {view.categoryId
                ? categories.find((c) => c.category_id === view.categoryId)?.name ?? "课程"
                : "未分类"}
            </div>

            <button
              type="button"
              className="sidebar-nav-action"
              onClick={() => setShowCreate(true)}
            >
              <Plus size={18} aria-hidden />
              <span>新建课程</span>
            </button>

            <div className="course-scroll-area">
              {loading && <div className="sidebar-hint">加载中…</div>}
              {error && !loading && <div className="sidebar-error-inline">无法加载课程</div>}
              {!loading &&
                !error &&
                courses.filter((c) => (c.category_id ?? null) === view.categoryId).length === 0 && (
                  <div className="course-empty">还没有课程</div>
                )}
              {courses
                .filter((c) => (c.category_id ?? null) === view.categoryId)
                .map((course) => (
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
                      setMenuOpenFor((prev) =>
                        prev === course.course_id ? null : course.course_id
                      )
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
                // 返回当前课程所属分类（或未分类），不回全部课程大列表
                const catId = workspaceCourse?.category_id ?? null;
                setView({ kind: "categoryCourses", categoryId: catId });
              }}
            >
              <ArrowLeft size={16} aria-hidden />
              <span>
                {workspaceCourse?.category_id
                  ? categories.find((c) => c.category_id === workspaceCourse.category_id)?.name ??
                    "分类"
                  : "未分类"}
              </span>
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
                <span className="sidebar-section-title">最近</span>
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
          defaultCategoryId={view.kind === "categoryCourses" ? view.categoryId : null}
          onClose={() => setShowCreate(false)}
          onCreated={(course) => {
            setShowCreate(false);
            loadCourses();
            onClose();
            navigateToCourse(course.course_id);
          }}
        />
      )}

      {showCreateCategory && (
        <CategoryNameModal
          title="新建分类"
          label="分类名称"
          initial=""
          confirmLabel="创建"
          onSubmit={async (name) => {
            const cat = await api.createCourseCategory(name);
            setCategories((prev) => [...prev, cat]);
            setShowCreateCategory(false);
          }}
          onClose={() => setShowCreateCategory(false)}
        />
      )}

      {renamingCategory && (
        <CategoryNameModal
          title="重命名分类"
          label="分类名称"
          initial={renamingCategory.name}
          confirmLabel="保存"
          onSubmit={async (name) => {
            const updated = await api.renameCourseCategory(renamingCategory.category_id, name);
            setCategories((prev) =>
              prev.map((c) => (c.category_id === updated.category_id ? updated : c))
            );
            setRenamingCategory(null);
          }}
          onClose={() => setRenamingCategory(null)}
        />
      )}

      {deletingCategory && (
        <DeleteCategoryDialog
          category={deletingCategory}
          onClose={() => setDeletingCategory(null)}
          onDeleted={() => {
            // 本地同步：分类移除；该分类下课程移到未分类（后端已保证课程/Adaptive 数据不删）
            setCategories((prev) =>
              prev.filter((c) => c.category_id !== deletingCategory.category_id)
            );
            setCourses((prev) =>
              prev.map((c) =>
                c.category_id === deletingCategory.category_id ? { ...c, category_id: null } : c
              )
            );
            setDeletingCategory(null);
            setView({ kind: "categoryList" });
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
