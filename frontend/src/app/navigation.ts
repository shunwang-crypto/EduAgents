/** LearningApp-relative 导航工具（宿主可挂任意前缀：/adaptive-learning/*、/host/learning/*、/）。
 *
 * 规则：URL 中若存在 "/courses/"，LearningApp 根路径为它之前的部分；否则为当前 pathname 本身。
 * 这样所有导航都由统一 helper 负责，页面不再各自拼绝对路径（如 "/courses/PY/chat"），
 * 避免宿主前缀（/adaptive-learning 等）下导航「跳出前缀」。
 */

/** 计算 LearningApp 根路径（General Chat 对应路由，空 path = AppShell index）。
 * 同时去除尾部多余 "/"，避免 base 为 "/host/learning/" 时拼出 "/host/learning//courses/..."。 */
export function learningAppBase(pathname: string): string {
  const idx = pathname.indexOf("/courses/");
  let base = idx < 0 ? (pathname || "/") : (idx === 0 ? "/" : pathname.slice(0, idx));
  if (base.length > 1 && base.endsWith("/")) {
    base = base.replace(/\/+$/, "");
  }
  return base;
}

/** 拼接 base（LearningApp 根，结尾无斜杠或为 "/"）与以 "/" 开头的相对后缀，避免出现双斜杠。 */
function joinPath(base: string, suffix: string): string {
  return base === "/" ? suffix : `${base}${suffix}`;
}

/** General Chat 根路径，可附带 conversation_id。 */
export function generalChatPath(pathname: string, conversationId?: string | null): string {
  const base = learningAppBase(pathname);
  const q = conversationId ? `?conversation=${encodeURIComponent(conversationId)}` : "";
  return `${base}${q}`;
}

/** 课程 Chat 路径，可附带 conversation_id 或 plan step。 */
export function courseChatPath(
  pathname: string,
  courseId: string,
  opts?: { conversationId?: string | null; stepId?: string | null }
): string {
  const base = learningAppBase(pathname);
  const params = new URLSearchParams();
  if (opts?.conversationId) params.set("conversation", opts.conversationId);
  if (opts?.stepId) params.set("step", opts.stepId);
  const q = params.toString();
  return `${joinPath(base, `/courses/${courseId}/chat`)}${q ? `?${q}` : ""}`;
}

/** 课程 Plan 路径。 */
export function coursePlanPath(pathname: string, courseId: string): string {
  const base = learningAppBase(pathname);
  return joinPath(base, `/courses/${courseId}/plan`);
}
