import { useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { Course } from "../../api/types";
import "./courses.css";

interface Props {
  onClose: () => void;
  onCreated: (course: Course) => void;
}

/** 新建课程 Modal：清晰字段式（课程主题 + 学习目标可选）。无障碍 dialog。 */
export function CreateCourseModal({ onClose, onCreated }: Props) {
  const api = useApi();
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const topicRef = useRef<HTMLInputElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const prevFocus = useRef<HTMLElement | null>(null);

  // 打开时记录焦点并自动聚焦 topic；Esc 关闭；Tab 焦点循环（focus trap）
  useEffect(() => {
    prevFocus.current = document.activeElement as HTMLElement | null;
    topicRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const modalEl = modalRef.current;
      if (!modalEl) return;
      const focusables = Array.from(
        modalEl.querySelectorAll<HTMLElement>(
          'button, input, textarea, [href], [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || active === null || !modalEl.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !modalEl.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prevFocus.current?.focus?.();
    };
  }, [onClose]);

  const submit = async () => {
    if (!topic.trim()) {
      setError("请输入课程主题");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const course = await api.createCourse({ topic: topic.trim(), goal: goal.trim() });
      onCreated(course);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败，请重试");
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={modalRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-course-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="create-course-title" className="modal-title">
          新建课程
        </h3>
        <label className="modal-label" htmlFor="course-topic">
          课程主题
        </label>
        <input
          id="course-topic"
          ref={topicRef}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Python 数据分析"
          autoComplete="off"
        />
        <label className="modal-label" htmlFor="course-goal">
          学习目标（可选）
        </label>
        <textarea
          id="course-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={2}
          placeholder="两周内掌握 pandas 并完成数据分析报告"
        />
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button ref={closeBtnRef} type="button" className="ea-button" onClick={onClose}>
            取消
          </button>
          <button type="button" className="ea-button primary" onClick={submit} disabled={loading}>
            {loading ? "创建中…" : "创建课程"}
          </button>
        </div>
      </div>
    </div>
  );
}
