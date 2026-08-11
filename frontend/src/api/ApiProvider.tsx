import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createApiClient, type ApiClient } from "./client";

/** ApiContext：宿主 userId → ApiClient（X-User-Id 头）的单一注入点。
 * 业务组件必须通过 useApi() 获取实例，禁止全局单例 / 写死用户。 */
const ApiContext = createContext<ApiClient | null>(null);

export function ApiProvider({ userId, children }: { userId: string; children: ReactNode }) {
  const api = useMemo(() => createApiClient(userId), [userId]);
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  const api = useContext(ApiContext);
  if (!api) {
    throw new Error("useApi must be used within ApiProvider");
  }
  return api;
}
