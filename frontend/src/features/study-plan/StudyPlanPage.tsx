import { useCallback, useEffect, useRef, useState } from "react";
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
import type { Course, PlanStep, StudyPlan } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { CourseHeader } from "../../layout/CourseHeader";
import { useLearningNav } from "../../app/useLearningNav";
import "./study-plan.css";

interface OutletCtx {
  openMobileSidebar: () => void;
}

interface LessonCache {
  markdown: string;
  generatedAt: string | null;
}

interface PlanSettingsFieldsProps {
  durationDays: number;
  dailyMinutes: number;
  background: string;
  onChange: (patch: {
    duration_days?: number;
    daily_minutes?: number;
    background?: string;
  }) => void;
}

/** 轻量计划设置字段：首次生成与重新生成共用，避免重复两套 input JSX。 */
function PlanSettingsFields({ durationDays, dailyMinutes, background, onChange }: PlanSettingsFieldsProps) {
  return (
    <>
      <label className="plan-settings-field">
        <span>学习周期（天）</span>
        <input
          type="number"
          min={1}
          max={365}
          value={durationDays}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!Number.isNaN(n)) onChange({ duration_days: Math.min(365, Math.max(1, n)) });
          }}
        />
      </label>
      <label className="plan-settings-field">
        <span>每日（分钟）</span>
        <input
          type="number"
          min={5}
          max={600}
          value={dailyMinutes}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!Number.isNaN(n)) onChange({ daily_minutes: Math.min(600, Math.max(5, n)) });
          }}
        />
      </label>
      <label className="plan-settings-field">
        <span>当前基础（可选）</span>
        <input
          type="text"
          value={background}
          placeholder="例如：我会基础 Python"
          onChange={(e) => onChange({ background: e.target.value })}
        />
      </label>
    </>
  );
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

  // 计划设置（周期/每日时长/当前基础）：首次生成落库，重新生成复用为默认
  const [settings, setSettings] = useState<{
    duration_days: number;
    daily_minutes: number;
    background: string;
  }>({
    duration_days: 14,
    daily_minutes: 60,
    background: "",
  });

  // 展开的 Lesson 步骤 + Lesson 缓存（懒加载，按 stepId 缓存，避免重复调 LLM）
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null);
  const [lessonByStep, setLessonByStep] = useState<Record<string, LessonCache>>({});
  const [lessonLoadingStep, setLessonLoadingStep] = useState<string | null>(null);
  const [lessonErrorStep, setLessonErrorStep] = useState<string | null>(null);
  const [lessonErrorKind, setLessonErrorKind] = useState<"stale" | "error" | null>(null);

  //  stale-async 保护：courseId 快速切换时，旧请求的响应不许覆盖新页面
  const loadSeq = useRef(0);
  //  Lesson 请求级 stale 保护：一次只保留最后一个 Lesson 响应，过期响应丢弃
  const lessonRequestSeq = useRef(0);

  useEffect(() => {
    if (!courseId) return;
    const seq = ++loadSeq.current;
    setCourseError(false);
    setError("");
    setPlanStatus("loading");
    setPlan(null);
    // 切换课程时清空 Lesson 展开/缓存，避免串课；并使进行中的 Lesson 请求失效
    setExpandedStepId(null);
    setLessonByStep({});
    setLessonErrorStep(null);
    setLessonErrorKind(null);
    setLessonLoadingStep(null);
    lessonRequestSeq.current++;
    api
      .getCourse(courseId)
      .then((c) => {
        if (seq === loadSeq.current) setCourse(c);
      })
      .catch(() => {
        if (seq === loadSeq.current) setCourseError(true);
      });
    api
      .getPlan(courseId)
      .then((p) => {
        if (seq !== loadSeq.current) return;
        // getPlan 解析为 null（无计划）也应进入 empty 态，而非 ready 空白页
        if (!p) {
          setPlanStatus("empty");
          return;
        }
        setPlan(p);
        setPlanStatus("ready");
      })
      .catch((e) => {
        if (seq !== loadSeq.current) return;
        // 404 = 还没有计划；其他错误（500 等）= 服务器问题，明确为 error 状态
        if (e instanceof ApiError && e.status === 404) {
          setPlanStatus("empty");
        } else {
          setPlanStatus("error");
          setError("无法加载学习计划，请重试");
        }
      });
  }, [courseId, api]);

  //  课程加载完成后同步计划设置默认值（来自课程已保存的周期/每日时长）
  useEffect(() => {
    if (course) {
      setSettings({
        duration_days: course.duration_days || 14,
        daily_minutes: course.daily_minutes || 60,
        background: "",
      });
    }
  }, [course]);

  const generate = useCallback(
    async (override?: { duration_days?: number; daily_minutes?: number; background?: string }) => {
      if (!courseId) return;
      setGenerating(true);
      setError("");
      try {
        const body = {
          duration_days: override?.duration_days ?? settings.duration_days,
          daily_minutes: override?.daily_minutes ?? settings.daily_minutes,
          background: override?.background ?? settings.background,
        };
        const p = await api.generatePlan(courseId, body);
        setPlan(p);
        setPlanStatus("ready");
        setShowMarkdown(false);
        setConfirmRegenerate(false);
        // 同步后端写回的设置
        if (p && typeof override?.duration_days === "number") {
          setSettings((s) => ({ ...s, duration_days: override.duration_days! }));
        }
        if (p && typeof override?.daily_minutes === "number") {
          setSettings((s) => ({ ...s, daily_minutes: override.daily_minutes! }));
        }
        // 当前基础（background）是一次性的画像事实，生成后清空输入
        setSettings((s) => ({ ...s, background: "" }));
      } catch (e) {
        setError(e instanceof Error ? e.message : "生成失败");
      } finally {
        setGenerating(false);
      }
    },
    [courseId, api, settings]
  );

  const toggleStep = useCallback(
    async (stepId: string, status: string): Promise<boolean> => {
      if (!courseId) return false;
      try {
        const p = await api.updateStep(courseId, stepId, status);
        setPlan(p);
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "更新失败");
        return false;
      }
    },
    [courseId, api]
  );

  //  懒加载 Lesson：展开时按需 GET-OR-GENERATE；已缓存则跳过；后端缓存（lesson_markdown）亦复用
  const openLesson = useCallback(
    async (stepId: string) => {
      if (!courseId) return;
      const reqSeq = ++lessonRequestSeq.current;
      setExpandedStepId(stepId);
      if (lessonByStep[stepId]?.markdown) return;
      const s = plan?.stages.flatMap((st) => st.steps).find((x) => x.step_id === stepId);
      if (s?.lesson_markdown) {
        setLessonByStep((prev) => ({
          ...prev,
          [stepId]: { markdown: s.lesson_markdown as string, generatedAt: s.lesson_generated_at },
        }));
        return;
      }
      setLessonLoadingStep(stepId);
      setLessonErrorStep((curr) => (curr === stepId ? null : curr));
      setLessonErrorKind(null);
      try {
        const res = await api.getLesson(courseId, stepId);
        // stale 保护：过期响应（课程/用户已切换、或已有更新的 Lesson 请求）直接丢弃
        if (reqSeq !== lessonRequestSeq.current) return;
        setLessonByStep((prev) => ({
          ...prev,
          [stepId]: { markdown: res.lesson_markdown, generatedAt: res.lesson_generated_at },
        }));
      } catch (e) {
        if (reqSeq !== lessonRequestSeq.current) return;
        const status = e instanceof ApiError ? e.status : 0;
        setLessonErrorKind(status === 404 ? "stale" : "error");
        setLessonErrorStep(stepId);
      } finally {
        if (reqSeq === lessonRequestSeq.current)
          setLessonLoadingStep((curr) => (curr === stepId ? null : curr));
      }
    },
    [courseId, api, plan, lessonByStep]
  );

  const handleStart = useCallback(
    async (step: PlanStep) => {
      if (step.status === "not_started") {
        const ok = await toggleStep(step.step_id, "in_progress");
        // status 更新本身失败 → 不继续生成 Lesson，避免 not_started + 已展开 lesson 状态冲突
        if (!ok) return;
      }
      await openLesson(step.step_id);
    },
    [toggleStep, openLesson]
  );
  const handleContinue = useCallback((step: PlanStep) => void openLesson(step.step_id), [openLesson]);
  const handleViewAgain = useCallback((step: PlanStep) => void openLesson(step.step_id), [openLesson]);
  const handleComplete = useCallback(
    (step: PlanStep) => void toggleStep(step.step_id, "completed"),
    [toggleStep]
  );

  const stages = plan?.stages?.length ? plan.stages : [];
  // progress 单一来源：Backend plan.progress（completed steps / total steps 已由后端算好）
  const rawProgress = typeof plan?.progress === "number" ? plan.progress : 0;
  const progressPct = Math.round(Math.max(0, Math.min(1, rawProgress)) * 100);

  // 路由不变量：courses/:courseId/plan 必须带 courseId，否则地址无效（提前 return，所有 hooks 已声明）。
  if (!courseId) {
    return (
      <>
        <CourseHeader course={null} activeView="plan" onOpenMobileSidebar={openMobileSidebar} />
        <div className="plan-scroll">
          <div className="plan-doc">
            <div className="inline-error" role="alert">
              课程地址无效
            </div>
          </div>
        </div>
      </>
    );
  }
  // 通过 guard 后，activeCourseId 是确定的 string，后续导航/请求统一使用，不再到处 courseId! / ?? ""
  const activeCourseId = courseId;

  const norm = (s: string) => s.trim().replace(/\s+/g, "");
  const showDescFor = (step: PlanStep) => {
    const d = step.description?.trim();
    if (!d) return false;
    //  dedup #27：描述与标题归一化后相同则不渲染（避免「标题：标题」冗余）
    return norm(d) !== norm(step.title);
  };

  const lessonForStep = (stepId: string): LessonCache => {
    const cached = lessonByStep[stepId];
    if (cached) return cached;
    const s = plan?.stages.flatMap((st) => st.steps).find((x) => x.step_id === stepId);
    return { markdown: s?.lesson_markdown || "", generatedAt: s?.lesson_generated_at ?? null };
  };

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

          {!courseError && planStatus === "loading" && (
            <div className="plan-skeleton" aria-busy="true">
              <div className="plan-skeleton-block" style={{ height: 28, width: "55%" }} />
              <div className="plan-skeleton-block" style={{ height: 14, width: "35%" }} />
              <div className="plan-skeleton-block" style={{ height: 4, width: "100%" }} />
              <div className="plan-skeleton-block" style={{ height: 12, width: "25%" }} />
            </div>
          )}

          {!courseError && planStatus === "error" && (
            <div className="inline-error" role="alert">
              {error || "无法加载学习计划，请重试"}
            </div>
          )}

          {!courseError && planStatus === "empty" && (
            <div className="plan-empty">
              <span className="plan-empty-icon">
                <BookOpen size={22} aria-hidden />
              </span>
              <h2>还没有学习计划</h2>
              <p>设置学习周期与时长，根据课程目标生成三阶段学习计划。</p>
              <div className="plan-settings plan-settings-empty">
                <PlanSettingsFields
                  durationDays={settings.duration_days}
                  dailyMinutes={settings.daily_minutes}
                  background={settings.background}
                  onChange={(patch) => setSettings((s) => ({ ...s, ...patch }))}
                />
              </div>
              <button className="ea-button primary" onClick={() => generate()} disabled={generating}>
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

          {!courseError && planStatus === "ready" && plan && (
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
                  {stage.steps.map((step) => {
                    const expanded = expandedStepId === step.step_id;
                    const lesson = lessonForStep(step.step_id);
                    const lessonLoading = lessonLoadingStep === step.step_id;
                    const lessonError = lessonErrorStep === step.step_id;
                    return (
                      <div
                        key={step.step_id}
                        className={`plan-step ${expanded ? "expanded" : ""}`}
                      >
                        <div className="plan-step-index">{String(step.seq).padStart(2, "0")}</div>
                        <div className="plan-step-body">
                          <div className="plan-step-title">{step.title}</div>
                          {showDescFor(step) && (
                            <div className="plan-step-desc">{step.description}</div>
                          )}
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
                              onClick={() =>
                                nav.openCourseChat(activeCourseId, { stepId: step.step_id })
                              }
                            >
                              <MessageCircleQuestion size={14} aria-hidden /> 就此提问
                            </button>
                          </div>

                          {/* 展开的 Lesson 讲解（懒加载） */}
                          {expanded && (
                            <div className="plan-step-lesson">
                              {lessonLoading && (
                                <div className="plan-lesson-loading" aria-busy="true">
                                  <LoaderCircle size={14} className="spin" aria-hidden /> 正在生成讲解…
                                </div>
                              )}
                              {lessonError && !lessonLoading && (
                                <div className="inline-error" role="alert">
                                  {lessonErrorKind === "stale"
                                    ? "该学习步骤已失效，请刷新计划"
                                    : "讲解生成失败"}
                                  <button
                                    type="button"
                                    className="lesson-retry"
                                    onClick={() => void openLesson(step.step_id)}
                                  >
                                    重试
                                  </button>
                                </div>
                              )}
                              {!lessonLoading && !lessonError && lesson.markdown && (
                                <RichMarkdown content={lesson.markdown} />
                              )}
                              {!lessonLoading && !lessonError && !lesson.markdown && (
                                <div className="plan-lesson-empty">本节暂无讲解</div>
                              )}
                              <div className="plan-lesson-footer">
                                {step.status !== "completed" && (
                                  <button
                                    type="button"
                                    className="ea-button primary"
                                    onClick={() => handleComplete(step)}
                                  >
                                    <CheckCircle2 size={14} aria-hidden /> 标记完成
                                  </button>
                                )}
                                <button
                                  type="button"
                                  className="ea-button"
                                  onClick={() => setExpandedStepId(null)}
                                >
                                  收起
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                        <div className="plan-step-status">
                          {step.status === "not_started" && (
                            <button
                              type="button"
                              className="step-status-control status-not-started"
                              onClick={() => handleStart(step)}
                            >
                              <Circle size={15} aria-hidden /> 开始学习
                            </button>
                          )}
                          {step.status === "in_progress" && (
                            <button
                              type="button"
                              className="step-status-control status-in-progress"
                              onClick={() => handleContinue(step)}
                            >
                              <CircleDot size={15} aria-hidden /> 继续学习
                            </button>
                          )}
                          {step.status === "completed" && (
                            <>
                              <span className="step-status-done">
                                <CheckCircle2 size={15} aria-hidden /> 已完成
                              </span>
                              <button
                                type="button"
                                className="step-status-control status-completed"
                                onClick={() => handleViewAgain(step)}
                              >
                                再次查看
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </section>
              ))}

              {/* 计划设置（周期 / 每日时长 / 当前基础）：重新生成时应用 */}
              <div className="plan-settings">
                <div className="plan-settings-title">计划设置</div>
                <PlanSettingsFields
                  durationDays={settings.duration_days}
                  dailyMinutes={settings.daily_minutes}
                  background={settings.background}
                  onChange={(patch) => setSettings((s) => ({ ...s, ...patch }))}
                />
                <span className="plan-settings-hint">重新生成时应用此设置</span>
              </div>

              {/* Footer actions */}
              <div className="plan-actions">
                <button
                  type="button"
                  className="ea-button"
                  onClick={() => setShowMarkdown((v) => !v)}
                >
                  {showMarkdown ? (
                    <ChevronUp size={15} aria-hidden />
                  ) : (
                    <ChevronDown size={15} aria-hidden />
                  )}
                  {showMarkdown ? "收起完整说明" : "查看完整说明"}
                </button>
                {confirmRegenerate ? (
                  <span className="plan-regen-confirm">
                    <span className="plan-regen-text">重新生成会替换当前计划，是否继续？</span>
                    <button
                      type="button"
                      className="ea-button primary"
                      onClick={() =>
                        generate({
                          duration_days: settings.duration_days,
                          daily_minutes: settings.daily_minutes,
                        })
                      }
                      disabled={generating}
                    >
                      确认重新生成
                    </button>
                    <button
                      type="button"
                      className="ea-button"
                      onClick={() => setConfirmRegenerate(false)}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="ea-button secondary"
                    onClick={() => setConfirmRegenerate(true)}
                    disabled={generating}
                  >
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

          {!courseError && planStatus === "ready" && error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
