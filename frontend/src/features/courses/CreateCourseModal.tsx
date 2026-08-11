import { useState } from "react";
import { api } from "../../api/client";
import type { Course } from "../../api/types";

interface Props {
  onClose: () => void;
  onCreated: (course: Course) => void;
}

/** 新建课程：简单 Modal（自然语言或字段）。 */
export function CreateCourseModal({ onClose, onCreated }: Props) {
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!topic.trim()) {
      setError("请输入想学习的内容，例如：Python 数据分析");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const course = await api.createCourse({ topic: topic.trim(), goal: goal.trim() });
      onCreated(course);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>新建课程</h3>
        <label>想学习什么？</label>
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="例如：我想两周学习 Python 数据分析"
          autoFocus
        />
        <label>学习目标（可选）</label>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={2}
          placeholder="例如：能独立完成数据分析报告"
        />
        {error && <p style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn primary" onClick={submit} disabled={loading}>
            {loading ? "创建中…" : "创建课程"}
          </button>
        </div>
      </div>
    </div>
  );
}
