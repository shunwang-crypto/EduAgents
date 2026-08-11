import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Course, StudyPlan } from "../../api/types";

const STATUS_LABEL: Record<string, string> = {
  not_started: "未开始",
  in_progress: "进行中",
  completed: "已完成",
};

/** StudyPlanPage：ChatGPT 文档式计划视图（无 Dashboard）。 */
export function StudyPlanPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Course | null>(null);
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!courseId) return;
    api.getCourse(courseId).then(setCourse).catch(() => setCourse(null));
    api
      .getPlan(courseId)
      .then(setPlan)
      .catch(() => setPlan(null));
  }, [courseId]);

  const generate = useCallback(async () => {
    if (!courseId) return;
    setGenerating(true);
    setError("");
    try {
      const p = await api.generatePlan(courseId, {});
      setPlan(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }, [courseId]);

  const toggleStep = useCallback(
    async (stepId: string, status: string) => {
      if (!courseId) return;
      try {
        const p = await api.updateStep(courseId, stepId, status);
        setPlan(p);
      } catch (e) {
        setError(e instanceof Error ? e.message : "更新失败");
      }
    },
    [courseId]
  );

  return (
    <div className="main">
      <header className="main-header">
        <h1>{course?.display_name ?? "学习计划"}</h1>
      </header>
      <div className="main-content">
        <div className="content-center">
          {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
          {!plan ? (
            <div className="empty-state">
              <h2>还没有学习计划</h2>
              <p>为你生成一份个性化学习计划（基于你的目标与已有背景）。</p>
              <button className="btn primary" onClick={generate} disabled={generating}>
                {generating ? "生成中…" : "生成学习计划"}
              </button>
            </div>
          ) : (
            <>
              <h2 style={{ margin: "0 0 4px" }}>{plan.title}</h2>
              <div className="plan-meta">{plan.summary || `${plan.steps.length} 个学习步骤`}</div>
              {plan.summary && <div className="plan-note">{plan.summary}</div>}

              <div>
                {plan.steps.map((step) => (
                  <div key={step.step_id} className="plan-step">
                    <div className="plan-step-index">{String(step.seq).padStart(2, "0")}</div>
                    <div className="plan-step-body">
                      <div className="plan-step-title">{step.title}</div>
                      {step.description && <div className="plan-step-desc">{step.description}</div>}
                      <div className="plan-step-meta">约 {step.minutes} 分钟</div>
                    </div>
                    <div className={`plan-step-status status-${step.status}`}>
                      {step.status === "completed" ? (
                        <button className="btn" onClick={() => toggleStep(step.step_id, "not_started")}>
                          ✓ 已完成
                        </button>
                      ) : (
                        <button className="btn" onClick={() => toggleStep(step.step_id, "completed")}>
                          ○ {STATUS_LABEL[step.status]}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 24 }}>
                <button className="btn" onClick={generate} disabled={generating}>
                  {generating ? "重新生成中…" : "重新生成计划"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
