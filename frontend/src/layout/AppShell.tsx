import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { MainLayout } from "./MainLayout";

/** ChatGPT 式外壳：Sidebar + 单一 Main Content（无第三栏）。 */
export function AppShell() {
  return (
    <div style={{ display: "flex", height: "100%" }}>
      <Sidebar />
      <MainLayout>
        <Outlet />
      </MainLayout>
    </div>
  );
}
