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
  Map,
  MessageCircleQuestion,
} from "lucide-react";
import { useApi, ApiError } from "../../api/ApiProvider";
import { subscribeCourseUpdated } from "../../api/courseEvents";
import type {
  Course,
  LearningMapNode,
  LearningMapResponse,
  PlanStep,
  StepExplanation,
  StudyPlan,
} from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { CourseHeader } from "../../layout/CourseHeader";
import { useLearningNav } from "../../app/useLearningNav";
import LearningMapView from "./LearningMap/LearningMapView";
import KnowledgeDetailPanel from "./LearningMap/KnowledgeDetailPanel";
import ExplanationWorkspace from "./explanation/ExplanationWorkspace";
import PlanBriefPanel from "./plan-brief/PlanBriefPanel";
import "./study-plan.css";

interface OutletCtx {
  openMobileSidebar: () => void;
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

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
}

function PlanGeneratingStatus({ elapsedSeconds }: { elapsedSeconds: number }) {
  return (
    <div
      className="plan-generating-status"
      role="status"
      aria-label="正在生成学习计划，请保持页面打开"
    >
      <div className="plan-generating-main">
        <LoaderCircle size={15} className="spin" aria-hidden />
        <span>正在分析目标、检索资料并整理学习路径</span>
        <span className="plan-generating-time" aria-hidden>
          已等待 {formatElapsed(elapsedSeconds)}
        </span>
      </div>
      <div className="plan-generating-hint">模型生成通常需要几分钟，请保持当前页面打开。</div>
    </div>
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
  const [generationElapsed, setGenerationElapsed] = useState(0);
  const [error, setError] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  // 课程目标（Active Goal 文本；后端 Course.current_goal 是唯一 Source of Truth）
  const [editingGoal, setEditingGoal] = useState(false);
  const [goalDraft, setGoalDraft] = useState("");
  const [savingGoal, setSavingGoal] = useState(false);
  const [goalError, setGoalError] = useState("");

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

  // 当前打开的 Structured Explanation（结构化讲解，非 lesson_markdown 长文）
  const [explanationStep, setExplanationStep] = useState<{
    stepId: string;
    kcId: string;
  } | null>(null);
  // Practice Handoff 待接入提示（feature flag；不实现练习）
  const [showHandoffNotice, setShowHandoffNotice] = useState(false);

  //  stale-async 保护：courseId 快速切换时，旧请求的响应不许覆盖新页面
  const loadSeq = useRef(0);
  //  scope 代际：courseId / api(user) 改变时自增；generate/toggleStep
  //  在 await 前后比对 scope，过期响应直接丢弃，避免串课污染
  const scopeSeq = useRef(0);

  // P0-1：Learning Map 请求必须独立生命周期，只能用新的 Learning Map 请求取消。
  //   mapRequestSeq 只由 map 请求相关代码自增，绝不与 course/plan/tutor 共享，
  //   避免 course/plan 请求把 map 请求的响应误判为过期而永久 loading。
  const mapRequestSeq = useRef(0);

  // Adaptive Learning Map 标签页
  const [tab, setTab] = useState<"map" | "plan">("map");
  const [learningMap, setLearningMap] = useState<LearningMapResponse | null>(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  //  无计划 / 无 graph（getLearningMap 404）→ empty state；真正的 server error 才显示错误
  const [mapEmpty, setMapEmpty] = useState(false);
  const [selectedKc, setSelectedKc] = useState<LearningMapNode | null>(null);

  const loadLearningMap = useCallback(
    async (reqMapSeq: number) => {
      if (!courseId) return;
      setMapLoading(true);
      setMapError(null);
      setMapEmpty(false);
      try {
        const data = await api.getLearningMap(courseId);
        if (reqMapSeq !== mapRequestSeq.current) return;
        setLearningMap(data);
        setMapEmpty(false);
        // 默认选中当前推荐 KC（current_recommended_kc，或 recommended_path[0]）
        const recId = data.current_recommended_kc ?? data.recommended_path?.[0];
        const rec = (recId ? data.nodes.find((n) => n.id === recId) : null) ?? null;
        setSelectedKc((prev) => {
          if (prev && data.nodes.some((n) => n.id === prev.id)) return prev;
          return rec;
        });
      } catch (e) {
        if (reqMapSeq !== mapRequestSeq.current) return;
        // 404 = 还没有生成学习计划 / KCGraph → empty state（非错误）
        const errStatus = (e as { status?: number } | null)?.status
          ?? (e instanceof ApiError ? e.status : 0);
        if (errStatus === 404) {
          setLearningMap(null);
          setMapEmpty(true);
          setSelectedKc(null);
        } else {
          setMapEmpty(false);
          setMapError(e instanceof Error ? e.message : "学习地图加载失败");
        }
      } finally {
        if (reqMapSeq === mapRequestSeq.current) setMapLoading(false);
      }
    },
    [courseId, api]
  );

  // P0-2：外部（generate / tutor）需要无参刷新 Map 时，始终开一个新的独立请求
  const refreshLearningMap = useCallback(() => {
    if (!courseId) return;
    const seq = ++mapRequestSeq.current;
    void loadLearningMap(seq);
  }, [courseId, loadLearningMap]);

  // 课程加载完成后拉取 Learning Map（独立生命周期，只被新的 Map 请求取消）
  useEffect(() => {
    if (!courseId) return;
    const seq = ++mapRequestSeq.current;
    void loadLearningMap(seq);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, api]);

  useEffect(() => {
    if (!courseId) return;
    const seq = ++loadSeq.current;
    scopeSeq.current++;
    setCourseError(false);
    setError("");
    setPlanStatus("loading");
    setPlan(null);
    setGenerating(false);
    setConfirmRegenerate(false);
    // 切换课程时清空旧 course：getCourse(B) 与 getPlan(B) 并行，B 加载完成前若仍保留 A 的
    // course（含 A 的 30/90 设置），一次抢先的「生成」会用 A 的设置去生成 B 的计划。
    setCourse(null);
    // 切换课程时清空 Explanation 打开态，避免串课
    setExplanationStep(null);
    setShowHandoffNotice(false);
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

  useEffect(() => {
    if (!generating) {
      setGenerationElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const updateElapsed = () => {
      setGenerationElapsed(Math.floor((Date.now() - startedAt) / 1000));
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [generating]);

  //  课程加载完成后同步计划设置默认值（来自课程已保存的周期/每日时长）
  useEffect(() => {
    if (course) {
      setSettings({
        duration_days: course.duration_days || 14,
        daily_minutes: course.daily_minutes || 60,
        background: "",
      });
      // 切换课程时重置目标编辑态（目标文本来自后端 Active Goal，不本地缓存）
      setEditingGoal(false);
      setGoalDraft(course.current_goal ?? "");
      setGoalError("");
    }
  }, [course]);

  useEffect(
    () =>
      subscribeCourseUpdated((event) => {
        if (event.courseId !== courseId) return;
        setCourse((current) =>
          current ? { ...current, display_name: event.displayName } : current
        );
      }),
    [courseId]
  );

  /** 保存课程目标：PATCH { goal } → 后端复用现有 Goal updater 更新 Active Goal（唯一 Source of Truth）。 */
  const saveGoal = useCallback(async () => {
    if (!courseId || !course) return;
    const reqScope = scopeSeq.current;
    setSavingGoal(true);
    setGoalError("");
    try {
      const updated = await api.renameCourse(courseId, { goal: goalDraft.trim() });
      if (reqScope !== scopeSeq.current) return;
      setCourse(updated);
      setEditingGoal(false);
    } catch (e) {
      if (reqScope !== scopeSeq.current) return;
      setGoalError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      if (reqScope === scopeSeq.current) setSavingGoal(false);
    }
  }, [courseId, api, course, goalDraft]);

  const generate = useCallback(
    async (override?: { duration_days?: number; daily_minutes?: number; background?: string }) => {
      if (!courseId) return;
      // course 尚未加载完成（切课途中）：禁止用旧 course 的设置生成新计划
      if (!course) return;
      const reqScope = scopeSeq.current;
      setGenerating(true);
      setConfirmRegenerate(false);
      setError("");
      try {
        const body = {
          duration_days: override?.duration_days ?? settings.duration_days,
          daily_minutes: override?.daily_minutes ?? settings.daily_minutes,
          background: override?.background ?? settings.background,
        };
        const p = await api.generatePlan(courseId, body);
        // 串课保护：生成期间切到别的课程，旧响应不许覆盖当前页面
        if (reqScope !== scopeSeq.current) return;
        setPlan(p);
        setPlanStatus("ready");
        setShowMarkdown(false);
        setConfirmRegenerate(false);
        // P0-2：生成计划成功后必须立即刷新 Learning Map（后端已生成 KCGraph），
        //  不能要求用户刷新页面。Map 请求有独立生命周期，不受本请求影响。
        refreshLearningMap();
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
        // 串课保护：过期响应的错误也不许污染当前页面
        if (reqScope !== scopeSeq.current) return;
        setError(e instanceof Error ? e.message : "生成失败");
      } finally {
        // 仅在仍属于当前 scope 时收尾 loading，避免清掉其他课程的 generating 态
        if (reqScope === scopeSeq.current) setGenerating(false);
      }
    },
    [courseId, api, settings, course, refreshLearningMap]
  );

  const toggleStep = useCallback(
    async (stepId: string, status: string): Promise<boolean> => {
      if (!courseId) return false;
      const reqScope = scopeSeq.current;
      try {
        const p = await api.updateStep(courseId, stepId, status);
        // 串课保护：更新期间切到别的课程，旧响应必须返回 false，
        // 否则外层 handleStart 会误以为成功而继续展开旧课程的 Lesson
        if (reqScope !== scopeSeq.current) return false;
        setPlan(p);
        return true;
      } catch (e) {
        if (reqScope !== scopeSeq.current) return false;
        setError(e instanceof Error ? e.message : "更新失败");
        return false;
      }
    },
    [courseId, api]
  );

  // Explanation Workspace 滚动锚点（§33：state 更新后再 scrollIntoView）
  const explanationRef = useRef<HTMLDivElement | null>(null);

  // §36：KC → PlanStep（优先 in_progress，then not_started，then completed，then lowest seq）
  const findPlanStepForKc = useCallback(
    (kcId: string): PlanStep | null => {
      if (!plan) return null;
      const steps = plan.stages.flatMap((st) => st.steps);
      const rank = (s: PlanStep) =>
        s.status === "in_progress" ? 0 : s.status === "not_started" ? 1 : s.status === "completed" ? 2 : 3;
      const matches = steps.filter((s) => s.kc_id === kcId);
      if (matches.length === 0) return null;
      return matches.slice().sort((a, b) => rank(a) - rank(b) || a.seq - b.seq)[0];
    },
    [plan]
  );

  // 打开 Structured Explanation Workspace（§16/§32：选中 KC + 切到 map + 立即进入 Workspace）
  const openExplanationStep = useCallback(
    (step: PlanStep) => {
      setShowHandoffNotice(false);
      setExplanationStep({ stepId: step.step_id, kcId: step.kc_id });
      if (learningMap) {
        const node = learningMap.nodes.find((n) => n.id === step.kc_id) ?? null;
        if (node) setSelectedKc(node);
      }
      setTab("map");
    },
    [learningMap]
  );

  // §32：设置 explanationStep 后，在 rAF 中 scrollIntoView
  useEffect(() => {
    if (!explanationStep) return;
    const raf = requestAnimationFrame(() => {
      explanationRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(raf);
  }, [explanationStep]);

  const openExplanation = openExplanationStep;

  // §35：根据 KC 讲解状态计算 CTA 文案
  const explanationCtaForKc = useCallback(
    (kcId: string): string | null => {
      if (!kcId) return null;
      const step = findPlanStepForKc(kcId);
      if (!step) return null;
      if (step.status === "completed") return "再次查看讲解";
      if (step.status === "in_progress") return "继续讲解";
      return "开始讲解";
    },
    [findPlanStepForKc]
  );

  const startExplanationForKc = useCallback(
    (kcId: string) => {
      const step = findPlanStepForKc(kcId);
      if (step) openExplanationStep(step);
    },
    [findPlanStepForKc, openExplanationStep]
  );

  // 请求一个 step 的 Structured Explanation（GET-OR-GENERATE，后端按 context_hash 缓存）
  const requestExplanation = useCallback(
    async (stepId: string): Promise<StepExplanation> => {
      if (!courseId || !plan) throw new Error("no plan loaded");
      return api.getExplanation(courseId, plan.plan_id, stepId);
    },
    [courseId, api, plan]
  );

  const handleStart = useCallback(
    async (step: PlanStep) => {
      if (step.status === "not_started") {
        const ok = await toggleStep(step.step_id, "in_progress");
        // status 更新失败 → 不继续打开讲解，避免 not_started + 已打开讲解状态冲突
        if (!ok) return;
      }
      openExplanation(step);
    },
    [toggleStep, openExplanation]
  );
  const handleContinue = useCallback((step: PlanStep) => void openExplanation(step), [openExplanation]);
  const handleViewAgain = useCallback((step: PlanStep) => void openExplanation(step), [openExplanation]);

  // Practice Handoff（§36/§92）：只定义入口；外部模块未接入 → placeholder 提示
  const handlePracticeHandoff = useCallback(() => {
    setShowHandoffNotice(true);
  }, []);

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

  // 课程目标是否存在（后端 Active Goal 文本；null/空串 = 未设置）
  const hasGoal = !!(course?.current_goal && course.current_goal.trim());

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

          {/* 课程目标（需求 B）：课程名下、计划设置之前；Active Goal 是唯一 Source of Truth */}
          {course && !courseError && (
            <section className="plan-goal">
              <div className="plan-goal-head">
                <span className="plan-goal-title">课程目标</span>
                {hasGoal && !editingGoal && (
                  <button
                    type="button"
                    className="plan-goal-edit-btn"
                    onClick={() => {
                      setGoalDraft(course.current_goal ?? "");
                      setEditingGoal(true);
                      setGoalError("");
                    }}
                  >
                    编辑
                  </button>
                )}
              </div>

              {!hasGoal && !editingGoal && (
                <div className="plan-goal-empty">
                  <p className="plan-goal-empty-text">还没有设置课程目标。</p>
                  <textarea
                    className="plan-goal-input"
                    rows={3}
                    value={goalDraft}
                    onChange={(e) => setGoalDraft(e.target.value)}
                    placeholder="例如：掌握 Pandas、NumPy 和数据分析流程，能够独立完成数据清洗与分析。"
                  />
                  <div className="plan-goal-actions">
                    <button
                      type="button"
                      className="ea-button primary"
                      disabled={savingGoal}
                      onClick={() => void saveGoal()}
                    >
                      {savingGoal ? "保存中…" : "保存目标"}
                    </button>
                  </div>
                </div>
              )}

              {hasGoal && !editingGoal && (
                <div className="plan-goal-text">{course.current_goal}</div>
              )}

              {editingGoal && (
                <div className="plan-goal-editing">
                  <textarea
                    className="plan-goal-input"
                    rows={3}
                    value={goalDraft}
                    onChange={(e) => setGoalDraft(e.target.value)}
                  />
                  <div className="plan-goal-actions">
                    <button
                      type="button"
                      className="ea-button"
                      onClick={() => setEditingGoal(false)}
                      disabled={savingGoal}
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      className="ea-button primary"
                      disabled={savingGoal}
                      onClick={() => void saveGoal()}
                    >
                      {savingGoal ? "保存中…" : "保存目标"}
                    </button>
                  </div>
                </div>
              )}

              {goalError && (
                <div className="inline-error" role="alert">
                  {goalError}
                </div>
              )}
            </section>
          )}

          {/* Adaptive Learning Map / 计划列表 双标签 */}
          <div className="plan-tabs" role="tablist" aria-label="学习计划视图">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "map"}
              className={`plan-tab ${tab === "map" ? "active" : ""}`}
              onClick={() => setTab("map")}
            >
              学习地图
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "plan"}
              className={`plan-tab ${tab === "plan" ? "active" : ""}`}
              onClick={() => setTab("plan")}
            >
              计划列表
            </button>
          </div>

          {tab === "plan" && (
            <>
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
              <button
                className="ea-button primary"
                onClick={() => generate()}
                disabled={course === null || generating || !hasGoal}
              >
                {generating ? (
                  <span className="loading-btn">
                    <LoaderCircle size={14} className="spin" aria-hidden /> 正在生成…
                  </span>
                ) : (
                  "生成学习计划"
                )}
              </button>
              {!hasGoal && (
                <div className="plan-goal-required-hint">请先设置课程目标。</div>
              )}
              {generating && <PlanGeneratingStatus elapsedSeconds={generationElapsed} />}
              {!generating && error && (
                <div className="inline-error plan-generate-error" role="alert">
                  {error}
                </div>
              )}
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

              {/* PlanBrief（§60：先知道“为什么这么学”，再看怎么走） */}
              <PlanBriefPanel brief={plan.plan_brief ?? null} />

              {/* 三阶段 */}
              {stages.map((stage) => (
                <section key={stage.stage_id} className="plan-stage">
                  <div className="plan-stage-head">
                    <div className="plan-stage-eyebrow">阶段 {stage.order}</div>
                    <h2 className="plan-stage-title">{stage.stage_title}</h2>
                  </div>
                  {stage.steps.map((step) => {
                    const isExplanationOpen = explanationStep?.stepId === step.step_id;
                    return (
                      <div
                        key={step.step_id}
                        className={`plan-step ${isExplanationOpen ? "expanded" : ""}`}
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
                            {/* §16：不再在列表内展开长文，而是打开结构化讲解 Workspace */}
                            <button
                              type="button"
                              className="step-ask-btn"
                              onClick={() => void handleStart(step)}
                            >
                              <BookOpen size={14} aria-hidden /> 查看讲解
                            </button>
                          </div>
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
                      disabled={course === null || generating}
                    >
                      确认重新生成
                    </button>
                    <button
                      type="button"
                      className="ea-button"
                      onClick={() => setConfirmRegenerate(false)}
                      disabled={generating}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="ea-button secondary"
                    onClick={() => setConfirmRegenerate(true)}
                    disabled={course === null || generating}
                  >
                    <LoaderCircle size={14} className={generating ? "spin" : ""} aria-hidden />
                    {generating ? "正在重新生成…" : "重新生成计划"}
                  </button>
                )}
              </div>

              {generating && <PlanGeneratingStatus elapsedSeconds={generationElapsed} />}

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
            </>
          )}

          {tab === "map" && (
            <div className="learning-map-layout">
              <div className="learning-map-canvas">
                {mapLoading && <div style={{ padding: 16, color: "#64748b" }}>加载学习地图…</div>}
                {mapError && (
                  <div className="learning-map-error" role="alert">
                    <p>学习地图暂时无法加载</p>
                    <button
                      type="button"
                      className="ea-button"
                      onClick={refreshLearningMap}
                    >
                      重试
                    </button>
                  </div>
                )}
                {mapEmpty && !mapLoading && !mapError && (
                  <div className="learning-map-empty">
                    <div className="learning-map-empty-icon">
                      <Map size={28} aria-hidden />
                    </div>
                    <h3>学习地图将在生成学习计划后创建</h3>
                    <p>
                      系统会根据你的目标生成知识依赖图，
                      并根据学习进度动态更新学习路径。
                    </p>
                    <button
                      type="button"
                      className="ea-button primary"
                      onClick={() => setTab("plan")}
                    >
                      生成学习计划
                    </button>
                  </div>
                )}
                {!mapLoading && !mapError && !mapEmpty && (
                  <LearningMapView
                    data={learningMap}
                    selectedKcId={selectedKc?.id ?? null}
                    onSelect={(kc) => setSelectedKc(kc)}
                  />
                )}
              </div>
              {!mapEmpty && (
                <aside className="learning-map-side">
                  <KnowledgeDetailPanel
                    node={selectedKc}
                    allNodes={learningMap?.nodes ?? []}
                    // §35：点击节点即可进入讲解（根据该 KC 对应 step 状态变化文案）
                    explanationCta={selectedKc ? explanationCtaForKc(selectedKc.id) : null}
                    onStartExplanation={() =>
                      selectedKc && startExplanationForKc(selectedKc.id)
                    }
                  />
                </aside>
              )}
            </div>
          )}

          {/* §34：只有选中某个知识点时才渲染 Explanation Workspace（不再空渲染） */}
          {explanationStep && (
            <section ref={explanationRef} className="explanation-section">
              <ExplanationWorkspace
                stepId={explanationStep?.stepId ?? ""}
                kcId={explanationStep?.kcId ?? ""}
                onRequestExplanation={requestExplanation}
                onBackToMap={() => {
                  setTab("map");
                  if (explanationStep?.kcId && learningMap) {
                    const node = learningMap.nodes.find((n) => n.id === explanationStep.kcId) ?? null;
                    if (node) setSelectedKc(node);
                  }
                }}
                onPracticeHandoff={handlePracticeHandoff}
              />
              {showHandoffNotice && (
                <div className="handoff-notice" role="status">
                  <p>
                    相关实践功能暂未开放。
                    <br />
                    <small>后续完成基础实践后，系统会根据学习记录更新你的知识掌握度。</small>
                  </p>
                  <button
                    type="button"
                    className="ea-button"
                    onClick={() => setShowHandoffNotice(false)}
                  >
                    关闭
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </>
  );
}
