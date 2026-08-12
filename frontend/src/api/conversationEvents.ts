/** 模块级对话更新事件总线。
 *
 * 用途：ChatPage 成功发消息后通知 Sidebar 刷新「最近对话」列表。
 * 必须 module-local（非 window / 非全局事件名），避免多宿主浏览器 tab / iframe 串扰。
 */
export interface ConversationUpdatedDetail {
  courseId?: string | null;
  conversationId?: string | null;
}

const target = new EventTarget();
const EVENT_NAME = "conversation-updated";

/** 通知对话列表已更新（新标题生成 / 新对话创建等）。 */
export function notifyConversationUpdated(detail?: ConversationUpdatedDetail): void {
  target.dispatchEvent(new CustomEvent<ConversationUpdatedDetail>(EVENT_NAME, { detail: detail ?? {} }));
}

/** 订阅对话更新事件，返回取消订阅函数。 */
export function subscribeConversationUpdated(
  handler: (detail: ConversationUpdatedDetail) => void,
): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<ConversationUpdatedDetail>).detail);
  target.addEventListener(EVENT_NAME, listener);
  return () => target.removeEventListener(EVENT_NAME, listener);
}
