import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  CircleDot,
  LoaderCircle,
  MessageCircleQuestion,
} from "lucide-react";
import { useApi, ApiError } from "../../api/ApiProvider";
import type { Course, StudyPlan } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { CourseHeader } from "../../layout/CourseHeader";
import { useLearningNav } from "../../app/useLearningNav";
import "./study-plan.css";

interface OutletCtx {
  openMobileSidebar: () => void;
}

/** StudyPlanPage：ChatGPT 文档式三阶段计划（无 Dashboard）。 */
export function StudyPlanPage() {
  const api = useApi();
  const nav = useLearningNav();
  const { courseId } = useParams<{ courseId: string }>();
  const { openMobileSidebar = () => {} } = (useOutletContext<OutletCtx>() ?? {});
  const [course, setCourse] = useState<Course | null>(null);
  const [courseError, setCourseError] = useState(false);
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  // 计划状态机：loading（加载中）/ empty（404 无计划）/ ready（有计划）/ error（500 等加载失败）。
  // 明确分离，避免 500 时「error」与「还没有学习计划」同时显示。
  const [planStatus, setPlanStatus] = useState<"loading" | "empty" | "ready" | "error">("loading");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);

  useEffect(() => {
    if (!courseId) return;
    setCourseError(false);
    setError("");
    api.getCourse(courseId).then(setCourse).catch(() => setCourseError(true));
    setPlanStatus("loading");
    setPlan(null);
    api
      .getPlan(courseId)
      .then((p) => {
        // getPlan 解析为 null（无计划）也应进入 empty 态，而非 ready 空白页
        if (!p) {
          setPlanStatus("empty");
          return;
        }
        setPlan(p);
        setPlanStatus("ready");
      })
      .catch((e) => {
        // 404 = 还没有计划；其他错误（500 等）= 服务器问题，明确为 error 状态
        if (e instanceof ApiError && e.status === 404) {
          setPlanStatus("empty");
        } else {
          setPlanStatus("error");
          setError("无法加载学习计划，请重试");
        }
      });
  }, [courseId, api]);

  const generate = useCallback(async () => {
    if (!courseId) return;
    setGenerating(true);
    setError("");
    try {
      const p = await api.generatePlan(courseId, {});
      setPlan(p);
      setPlanStatus("ready");
      setShowMarkdown(false);
      setConfirmRegenerate(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }, [courseId, api]);

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
    [courseId, api]
  );

  const stages = plan?.stages?.length ? plan.stages : [];
  // progress 单一来源：Backend plan.progress（completed steps / total steps 已由后端算好）
  const rawProgress = typeof plan?.progress === "number" ? plan.progress : 0;
  const progressPct = Math.round(Math.max(0, Math.min(1, rawProgress)) * 100);

  return (
    <>
      <CourseHeader course={course} activeView="plan" onOpenMobileSidebar={openMobileSidebar} />

      <div className="plan-scroll">
        <div className="plan-doc">
          {courseError && !course && (
            <div className="inline-error" role="alert">
              无法加载课程
            </div>
          )}

          {planStatus === "loading" && (
            <div className="plan-skeleton" aria-busy="true">
              <div className="plan-skeleton-block" style={{ height: 28, width: "55%" }} />
              <div className="plan-skeleton-block" style={{ height: 14, width: "35%" }} />
              <div className="plan-skeleton-block" style={{ height: 4, width: "100%" }} />
              <div className="plan-skeleton-block" style={{ height: 12, width: "25%" }} />
            </div>
          )}

          {planStatus === "error" && (
            <div className="inline-error" role="alert">
              {error || "无法加载学习计划，请重试"}
            </div>
          )}

          {planStatus === "empty" && (
            <div className="plan-empty">
              <span className="plan-empty-icon">
                <BookOpen size={22} aria-hidden />
              </span>
              <h2>还没有学习计划</h2>
              <p>根据课程目标生成三阶段学习计划。</p>
              <button className="ea-button primary" onClick={generate} disabled={generating}>
                {generating ? (
                  <span className="loading-btn">
                    <LoaderCircle size={14} className="spin" aria-hidden /> 正在生成…
                  </span>
                ) : (
                  "生成学习计划"
                )}
              </button>
              {generating && <div className="plan-generating-note">正在分析学习目标并拆解内容</div>}
            </div>
          )}

          {planStatus === "ready" && plan && (
            <>
              {/* Hero */}
              <div className="plan-hero">
                <h1>{plan.title || `${course?.display_name ?? ""}学习计划`}</h1>
                <div className="plan-hero-meta">{plan.summary}</div>
                <div className="plan-progress">
                  <div className="plan-progress-bar">
                    <div className="plan-progress-fill" style={{ width: `${progressPct}%` }} />
                  </div>
                  <div className="plan-progress-label">{progressPct}% 完成</div>
                </div>
              </div>

              {/* 三阶段 */}
              {stages.map((stage) => (
                <section key={stage.stage_id} className="plan-stage">
                  <div className="plan-stage-head">
                    <div className="plan-stage-eyebrow">阶段 {stage.order}</div>
                    <h2 className="plan-stage-title">{stage.stage_title}</h2>
                  </div>
                  {stage.steps.map((step) => (
                    <div key={step.step_id} className="plan-step">
                      <div className="plan-step-index">{String(step.seq).padStart(2, "0")}</div>
                      <div className="plan-step-body">
                        <div className="plan-step-title">{step.title}</div>
                        {step.description && <div className="plan-step-desc">{step.description}</div>}
                        {(step.learning_objective || (step.prerequisites?.length ?? 0) > 0) && (
                          <div className="plan-step-metas">
                            {step.learning_objective && (
                              <div className="plan-step-meta-row">
                                <span className="meta-label">目标</span>
                                <span>{step.learning_objective}</span>
                              </div>
                            )}
                            {step.prerequisites && step.prerequisites.length > 0 && (
                              <div className="plan-step-meta-row">
                                <span className="meta-label">前置</span>
                                <span>{step.prerequisites.join("、")}</span>
                              </div>
                            )}
                          </div>
                        )}
                        <div className="plan-step-footer">
                          <span className="plan-step-time">约 {step.minutes} 分钟</span>
                          <button
                            type="button"
                            className="step-ask-btn"
                            onClick={() => nav.openCourseChat(courseId, { stepId: step.step_id })}
                          >
                            <MessageCircleQuestion size={14} aria-hidden /> 就此提问
                          </button>
                        </div>
                      </div>
                      <div className="plan-step-status">
                        {step.status === "not_started" && (
                          <button
                            type="button"
                            className="step-status-control status-not-started"
                            onClick={() => toggleStep(step.step_id, "in_progress")}
                          >
                            <Circle size={15} aria-hidden /> 开始学习
                          </button>
                        )}
                        {step.status === "in_progress" && (
                          <button
                            type="button"
                            className="step-status-control status-in-progress"
                            onClick={() => toggleStep(step.step_id, "completed")}
                          >
                            <CircleDot size={15} aria-hidden /> 进行中
                          </button>
                        )}
                        {step.status === "completed" && (
                          <button
                            type="button"
                            className="step-status-control status-completed"
                            onClick={() => toggleStep(step.step_id, "not_started")}
                          >
                            <CheckCircle2 size={15} aria-hidden /> 已完成
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </section>
              ))}

              {/* Footer actions */}
              <div className="plan-actions">
                <button type="button" className="ea-button" onClick={() => setShowMarkdown((v) => !v)}>
                  {showMarkdown ? <ChevronUp size={15} aria-hidden /> : <ChevronDown size={15} aria-hidden />}
                  {showMarkdown ? "收起完整说明" : "查看完整说明"}
                </button>
                {confirmRegenerate ? (
                  <span className="plan-regen-confirm">
                    <span className="plan-regen-text">重新生成会替换当前计划，是否继续？</span>
                    <button type="button" className="ea-button primary" onClick={generate} disabled={generating}>
                      确认重新生成
                    </button>
                    <button type="button" className="ea-button" onClick={() => setConfirmRegenerate(false)}>
                      取消
                    </button>
                  </span>
                ) : (
                  <button type="button" className="ea-button secondary" onClick={() => setConfirmRegenerate(true)} disabled={generating}>
                    <LoaderCircle size={14} className={generating ? "spin" : ""} aria-hidden /> 重新生成计划
                  </button>
                )}
              </div>

              {showMarkdown && plan.plan_markdown && (
                <div className="plan-markdown-full">
                  <RichMarkdown content={plan.plan_markdown} />
                </div>
              )}
            </>
          )}

          {planStatus === "ready" && error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
