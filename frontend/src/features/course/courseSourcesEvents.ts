/** 模块级「课程资料」抽屉开关事件总线（module-local，非 window，避免跨宿主串扰）。
 * 两个入口（Sidebar 课程工作区「课程资料」、CourseHeader「···」）都调用 openCourseSources，
 * 由 AppShell 渲染的 CourseSourcesDrawer 订阅并打开同一抽屉。 */
const target = new EventTarget();
const OPEN = "open-course-sources";

export function openCourseSources(courseId: string): void {
  target.dispatchEvent(new CustomEvent<{ courseId: string }>(OPEN, { detail: { courseId } }));
}

export function subscribeCourseSourcesOpen(handler: (courseId: string) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<{ courseId: string }>).detail.courseId);
  target.addEventListener(OPEN, listener);
  return () => target.removeEventListener(OPEN, listener);
}
