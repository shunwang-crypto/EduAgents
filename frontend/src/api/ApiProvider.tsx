import { useEffect } from "react";
import { setApiUserId } from "./client";

/** ApiProvider：把宿主 userId 注入 ApiClient（X-User-Id 头）。
 * 业务组件继续 import { api }，但身份由 Provider 动态控制，不再写死。 */
export function ApiProvider({ userId, children }: { userId: string; children: React.ReactNode }) {
  useEffect(() => {
    setApiUserId(userId);
  }, [userId]);
  return <>{children}</>;
}
