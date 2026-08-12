import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { CourseSourcesDrawer } from "../features/course/CourseSourcesDrawer";
import { useApi } from "../api/ApiProvider";
import { useLearningNav } from "../app/useLearningNav";
import "./shell.css";

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** AppShell：ChatGPT 式外壳。唯一结构：
 * .eduagents-app > Sidebar + .workspace > Outlet
 * - sidebarCollapsed（桌面）与 mobileSidebarOpen（抽屉）独立管理；
 * - effectiveCollapsed：移动端恒 false（抽屉永远显示完整文案，不继承 desktop collapse）；
 * - 所有 navigate 使用相对路径，宿主可挂载到任意前缀。
 */
export function AppShell() {
  const api = useApi();
  const nav = useLearningNav();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [newChatError, setNewChatError] = useState(false);
  const isMobile = useMediaQuery("(max-width: 768px)");

  const newChat = async () => {
    try {
      setNewChatError(false);
      const conv = await api.createConversation(null);
      // 「新对话」= General Chat：导航到 LearningApp 根（脱离课程路由），
      // 不再停留在 courses/:courseId/chat（否则 course_id 与 conversation.course_id=null 不匹配 → 404）。
      nav.openGeneralChat(conv.conversation_id, true);
    } catch {
      // 新建对话失败：不假装成功，保持当前页面并提示
      setNewChatError(true);
    }
  };

  return (
    <div className="eduagents-app">
      {newChatError && (
        <div className="shell-notice" role="alert">
          新建对话失败，请重试
        </div>
      )}
      <Sidebar
        open={mobileSidebarOpen}
        collapsed={isMobile ? false : sidebarCollapsed}
        onClose={() => setMobileSidebarOpen(false)}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        newChat={newChat}
        navigateToCourse={(id) => nav.openCourseChat(id)}
      />
      <main className="workspace">
        <Outlet context={{ openMobileSidebar: () => setMobileSidebarOpen(true) }} />
      </main>
      {/* 课程资料抽屉：Sidebar 课程工作区「课程资料」与 CourseHeader「···」共用 */}
      <CourseSourcesDrawer />
    </div>
  );
}
