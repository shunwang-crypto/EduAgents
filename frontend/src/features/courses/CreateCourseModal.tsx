import { useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { Course, CourseCategory } from "../../api/types";
import "./courses.css";

interface Props {
  onClose: () => void;
  onCreated: (course: Course) => void;
  /** 当前分类上下文（可选）：从某分类进入时自动预选该分类；仍可手动修改。 */
  defaultCategoryId?: string | null;
}

/** 新建课程 Modal：课程名称 + 学习目标（可选）+ 分类（可选）。无障碍 dialog。
 * 分类是纯组织层（用户自己创建的 CourseCategory 列表，绝不硬编码 Python/Java/AI）。 */
export function CreateCourseModal({ onClose, onCreated, defaultCategoryId = null }: Props) {
  const api = useApi();
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [categories, setCategories] = useState<CourseCategory[]>([]);
  // "" = 未分类（category_id 为 null）
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>(defaultCategoryId ?? "");
  const [loading, setLoading] = useState(false);
  const loadingRef = useRef(false);
  const [error, setError] = useState("");
  const topicRef = useRef<HTMLInputElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const prevFocus = useRef<HTMLElement | null>(null);

  // 分类下拉选项（纯组织层；加载失败静默降级为只有「未分类」）
  useEffect(() => {
    let alive = true;
    api
      .listCourseCategories()
      .then((list) => {
        if (alive) setCategories(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api]);

  // 打开时记录焦点并自动聚焦 topic；Esc 关闭；Tab 焦点循环（focus trap）
  useEffect(() => {
    prevFocus.current = document.activeElement as HTMLElement | null;
    topicRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loadingRef.current) {
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
    loadingRef.current = true;
    setError("");
    try {
      const course = await api.createCourse({
        topic: topic.trim(),
        goal: goal.trim(),
        category_id: selectedCategoryId || null,
      });
      onCreated(course);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败，请重试");
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
        <form onSubmit={handleSubmit}>
        <label className="modal-label" htmlFor="course-topic">
          课程名称
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
        <label className="modal-label" htmlFor="course-category">
          分类（可选）
        </label>
        <select
          id="course-category"
          value={selectedCategoryId}
          onChange={(e) => setSelectedCategoryId(e.target.value)}
        >
          <option value="">未分类</option>
          {categories.map((cat) => (
            <option key={cat.category_id} value={cat.category_id}>
              {cat.name}
            </option>
          ))}
        </select>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button ref={closeBtnRef} type="button" className="ea-button" onClick={onClose} disabled={loading}>
            取消
          </button>
          <button type="submit" className="ea-button primary" disabled={loading}>
            {loading ? "创建中…" : "创建课程"}
          </button>
        </div>
        </form>
      </div>
    </div>
  );
}
