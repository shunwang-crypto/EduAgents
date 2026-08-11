import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Course, StudyPlan } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";

/** StudyPlanPage：ChatGPT 文档式三阶段计划视图（无 Dashboard）。
 * 每个 Step：状态 + 就此提问；「查看完整计划」展开 RichMarkdown。
 */
export function StudyPlanPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const [course, setCourse] = useState<Course | null>(null);
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);

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
      setShowMarkdown(false);
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

  const stages = plan?.stages?.length ? plan.stages : [];

  return (
    <div className="main">
      <header className="main-header">
        <h1>{course?.display_name ?? "学习计划"}</h1>
        {courseId && (
          <Link to={`/courses/${courseId}/chat`} className="btn">
            对话
          </Link>
        )}
      </header>
      <div className="main-content">
        <div className="content-center plan-doc">
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

              {/* 三阶段文档式渲染 */}
              {stages.map((stage) => (
                <section key={stage.stage_id} className="plan-stage">
                  <h3 className="plan-stage-title">
                    {stage.order}. {stage.stage_title}
                  </h3>
                  <div className="plan-stage-line" />
                  {stage.steps.map((step, i) => (
                    <div key={step.step_id} className="plan-step">
                      <div className="plan-step-index">{String(step.seq).padStart(2, "0")}</div>
                      <div className="plan-step-body">
                        <div className="plan-step-title">{step.title}</div>
                        {step.description && <div className="plan-step-desc">{step.description}</div>}
                        {step.learning_objective && (
                          <div className="plan-step-objective">目标：{step.learning_objective}</div>
                        )}
                        {step.prerequisites?.length > 0 && (
                          <div className="plan-step-prereq">
                            前置：{step.prerequisites.join("、")}
                          </div>
                        )}
                        <div className="plan-step-meta">约 {step.minutes} 分钟</div>
                        <button
                          type="button"
                          className="step-ask-btn"
                          onClick={() => navigate(`/courses/${courseId}/chat?step=${step.step_id}`)}
                        >
                          就此提问
                        </button>
                      </div>
                      <div className={`plan-step-status status-${step.status}`}>
                        {step.status === "not_started" && (
                          <button className="btn" onClick={() => toggleStep(step.step_id, "in_progress")}>
                            ○ 开始学习
                          </button>
                        )}
                        {step.status === "in_progress" && (
                          <button className="btn" onClick={() => toggleStep(step.step_id, "completed")}>
                            ◐ 标记完成
                          </button>
                        )}
                        {step.status === "completed" && (
                          <button className="btn" onClick={() => toggleStep(step.step_id, "not_started")}>
                            ✓ 已完成（重置）
                          </button>
                        )}
                      </div>
                      {i < stage.steps.length - 1 && <div className="plan-step-gap" />}
                    </div>
                  ))}
                </section>
              ))}
              {stages.length === 0 && (
                <div className="plan-step">
                  <div className="plan-step-body">
                    {plan.steps.map((step) => (
                      <div key={step.step_id} style={{ padding: "8px 0" }}>
                        {String(step.seq).padStart(2, "0")} {step.title}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap" }}>
                <button className="btn" onClick={() => setShowMarkdown((v) => !v)}>
                  {showMarkdown ? "收起完整计划" : "查看完整计划"}
                </button>
                <button className="btn" onClick={generate} disabled={generating}>
                  {generating ? "重新生成中…" : "重新生成计划"}
                </button>
              </div>

              {showMarkdown && plan.plan_markdown && (
                <div className="plan-markdown-full">
                  <RichMarkdown content={plan.plan_markdown} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
