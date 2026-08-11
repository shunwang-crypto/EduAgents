import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { MainLayout } from "./MainLayout";

/** ChatGPT 式外壳：Sidebar + 单一 Main Content（无第三栏）。
 * sidebarOpen/collapsed 由 AppShell 管理，供移动端 hamburger 与桌面折叠使用。
 */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const [collapsed, setCollapsed] = useState(false); // desktop collapse

  return (
    <div className="eduagents-app" style={{ display: "flex", height: "100%" }}>
      <Sidebar
        open={sidebarOpen}
        collapsed={collapsed}
        onClose={() => setSidebarOpen(false)}
        onToggleCollapse={() => setCollapsed((v) => !v)}
      />
      <MainLayout onOpenSidebar={() => setSidebarOpen(true)}>
        <Outlet />
      </MainLayout>
    </div>
  );
}
