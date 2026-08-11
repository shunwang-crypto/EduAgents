import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  onOpenSidebar: () => void;
}

/** MainLayout：单一 Main Content。<=768px 时显示 hamburger 打开 Sidebar Drawer。 */
export function MainLayout({ children, onOpenSidebar }: Props) {
  return (
    <main className="main">
      <button
        type="button"
        className="main-hamburger"
        onClick={onOpenSidebar}
        aria-label="打开菜单"
      >
        ☰
      </button>
      {children}
    </main>
  );
}
