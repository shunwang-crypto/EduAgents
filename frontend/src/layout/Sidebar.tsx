import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Course } from "../api/types";
import { CreateCourseModal } from "../features/courses/CreateCourseModal";

/** Sidebar：EduAgents + 新对话 + 我的课程 + 新建课程（ChatGPT 极简风格）。 */
export function Sidebar() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();

  const load = () => api.listCourses().then(setCourses).catch(() => setCourses([]));
  useEffect(() => {
    load();
  }, []);

  const onCreated = async () => {
    setShowCreate(false);
    await load();
  };

  return (
    <>
      <aside className={`sidebar ${collapsed ? "collapsed" : ""} ${mobileOpen ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="sidebar-brand">EduAgents</span>
          <button
            className="sidebar-collapse-btn"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "展开" : "收起"}
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <NavLink
          to="/"
          className={({ isActive }) => `sidebar-item ${isActive && !window.location.pathname.includes("/courses/") ? "active" : ""}`}
          onClick={() => setMobileOpen(false)}
        >
          <span className="icon">+</span> <span>新对话</span>
        </NavLink>

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
            onClick={() => setMobileOpen(false)}
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

      {mobileOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.3)",
            zIndex: 40,
          }}
          onClick={() => setMobileOpen(false)}
        />
      )}

      {showCreate && (
        <CreateCourseModal
          onClose={() => setShowCreate(false)}
          onCreated={(course) => {
            onCreated();
            navigate(`/courses/${course.course_id}/chat`);
          }}
        />
      )}
    </>
  );
}
