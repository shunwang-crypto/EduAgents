import { useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useApi } from "../api/ApiProvider";
import "./shell.css";

/** AppShell：ChatGPT 式外壳。唯一结构：
 * .eduagents-app > Sidebar + .workspace > Outlet
 * sidebarCollapsed（桌面）与 mobileSidebarOpen（抽屉）由 AppShell 统一管理。
 */
export function AppShell() {
  const api = useApi();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const navigate = useNavigate();

  const newChat = async () => {
    try {
      const conv = await api.createConversation(null);
      navigate(`/?conversation=${conv.conversation_id}`);
    } catch {
      navigate("/");
    }
  };

  return (
    <div className="eduagents-app">
      <Sidebar
        open={mobileSidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={() => setMobileSidebarOpen(false)}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        newChat={newChat}
        navigateToCourse={(id) => navigate(`/courses/${id}/chat`)}
      />
      <main className="workspace">
        <Outlet context={{ openMobileSidebar: () => setMobileSidebarOpen(true) }} />
      </main>
    </div>
  );
}
