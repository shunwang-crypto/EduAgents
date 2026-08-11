import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Course } from "../api/types";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";

interface SidebarProps {
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  onToggleCollapse: () => void;
}

/** Sidebar：EduAgents + 新对话（真新建 conversation）+ 我的课程 + 新建课程。
 * 移动端由 AppShell 控制 open（Drawer），点击课程/新对话后自动关闭。 */
export function Sidebar({ open, collapsed, onClose, onToggleCollapse }: SidebarProps) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const navigate = useNavigate();

  const load = () => api.listCourses().then(setCourses).catch(() => setCourses([]));
  useEffect(() => {
    load();
  }, []);

  // 「新对话」：真正创建新 conversation，跳转到 /?conversation=CONV-xxx
  const newChat = async () => {
    try {
      const conv = await api.createConversation(null);
      onClose();
      navigate(`/?conversation=${conv.conversation_id}`);
    } catch {
      onClose();
      navigate("/");
    }
  };

  const onCreated = async () => {
    setShowCreate(false);
    await load();
  };

  return (
    <>
      <aside className={`sidebar ${collapsed ? "collapsed" : ""} ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="sidebar-brand">EduAgents</span>
          <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title={collapsed ? "展开" : "收起"}>
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <button
          type="button"
          className={`sidebar-item sidebar-new-chat ${!window.location.pathname.includes("/courses/") ? "active" : ""}`}
          onClick={newChat}
        >
          <span className="icon">+</span> <span>新对话</span>
        </button>

        <div className="sidebar-section">
          <span>我的课程</span>
          <button className="icon-btn" onClick={() => setShowCreate(true)} title="新建课程">
            +
          </button>
        </div>

        {courses.map((course) => (
          <NavLink
            key={course.course_id}
            to={`/courses/${course.course_id}/chat`}
            className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}
            onClick={onClose}
          >
            <span className="icon">📚</span> <span>{course.display_name}</span>
          </NavLink>
        ))}

        <div className="sidebar-section">
          <button className="icon-btn" onClick={() => setShowCreate(true)} title="新建课程">
            <span style={{ fontSize: 12 }}>＋ 新建课程</span>
          </button>
        </div>
      </aside>

      {open && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-label="关闭侧边栏"
        />
      )}

      {showCreate && (
        <CreateCourseModal
          onClose={() => setShowCreate(false)}
          onCreated={(course) => {
            onCreated();
            onClose();
            navigate(`/courses/${course.course_id}/chat`);
          }}
        />
      )}
    </>
  );
}
