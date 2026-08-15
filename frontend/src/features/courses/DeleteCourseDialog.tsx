import { useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { Course } from "../../api/types";
import "./courses.css";

interface Props {
  course: Course;
  onClose: () => void;
  onDeleted: (courseId: string) => void;
}

/** 删除课程确认 Dialog：显式二次确认，提交调用 deleteCourse，成功后回调让父组件从列表移除。 */
export function DeleteCourseDialog({ course, onClose, onDeleted }: Props) {
  const api = useApi();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const loadingRef = useRef(false);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loadingRef.current) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const confirm = async () => {
    setLoading(true);
    setError("");
    loadingRef.current = true;
    try {
      await api.deleteCourse(course.course_id);
      onDeleted(course.course_id);
    } catch (e) {
      // 失败保持对话框，便于重试
      setError(e instanceof Error ? e.message : "删除失败，请稍后重试");
      setLoading(false);
      loadingRef.current = false;
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => !loading && onClose()}>
      <div
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-course-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="delete-course-title" className="modal-title">
          删除课程
        </h3>
        <p className="modal-text">
          确定要删除「{course.display_name}」吗？该课程的计划与学习记录将被移除，且无法恢复。
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button ref={cancelRef} type="button" className="ea-button" onClick={onClose} disabled={loading}>
            取消
          </button>
          <button type="button" className="ea-button danger" onClick={confirm} disabled={loading}>
            {loading ? "删除中…" : "删除课程"}
          </button>
        </div>
      </div>
    </div>
  );
}
