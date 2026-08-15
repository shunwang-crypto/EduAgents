/** 模块级课程更新事件总线：让 Sidebar 重命名后同步当前课程页标题。 */
export interface CourseUpdatedEvent {
  courseId: string;
  displayName: string;
}

type Listener = (event: CourseUpdatedEvent) => void;

const listeners = new Set<Listener>();

export function notifyCourseUpdated(event: CourseUpdatedEvent): void {
  listeners.forEach((listener) => listener(event));
}

export function subscribeCourseUpdated(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
