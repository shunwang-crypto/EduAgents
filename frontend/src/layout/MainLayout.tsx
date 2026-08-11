import type { ReactNode } from "react";

/** MainLayout：单一 Main Content（支持宿主 height:100% 容器）。 */
export function MainLayout({ children }: { children: ReactNode }) {
  return <main className="main">{children}</main>;
}
