import { useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { Course } from "../../api/types";
import "./courses.css";

interface Props {
  course: Course;
  onClose: () => void;
  onRenamed: (courseId: string, newName: string) => void;
}

/** 重命名课程 Modal：预填当前课程名，提交调用 renameCourse，成功后回调让父组件就地更新状态（不刷新列表）。 */
export function RenameCourseModal({ course, onClose, onRenamed }: Props) {
  const api = useApi();
  const [title, setTitle] = useState(course.display_name);
  const [loading, setLoading] = useState(false);
  const loadingRef = useRef(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loadingRef.current) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async () => {
    const next = title.trim();
    if (!next) {
      setError("课程名不能为空");
      return;
    }
    if (next === course.display_name) {
      onClose();
      return;
    }
    setLoading(true);
    loadingRef.current = true;
    setError("");
    try {
      await api.renameCourse(course.course_id, { display_name: next });
      onRenamed(course.course_id, next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败，请重试");
      setLoading(false);
      loadingRef.current = false;
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit();
  };

  return (
    <div className="modal-backdrop" onClick={() => !loading && onClose()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rename-course-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="rename-course-title" className="modal-title">
          重命名课程
        </h3>
        <form onSubmit={handleSubmit}>
          <label className="modal-label" htmlFor="course-rename">
            课程名
          </label>
          <input
            id="course-rename"
            ref={inputRef}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Python 数据分析"
            autoComplete="off"
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button ref={closeBtnRef} type="button" className="ea-button" onClick={onClose} disabled={loading}>
              取消
            </button>
            <button type="submit" className="ea-button primary" disabled={loading}>
              {loading ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
