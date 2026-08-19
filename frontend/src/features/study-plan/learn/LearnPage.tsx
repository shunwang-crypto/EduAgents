import { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { ArrowLeft, LoaderCircle, MessageCircleQuestion } from "lucide-react";
import { useApi } from "../../../api/ApiProvider";
import type { Course, PlanStep, StepExplanation, StudyPlan } from "../../../api/types";
import { CourseHeader } from "../../../layout/CourseHeader";
import { useLearningNav } from "../../../app/useLearningNav";
import ExplanationDocument from "../explanation/ExplanationDocument";
import "../study-plan.css";

interface OutletCtx {
  openMobileSidebar: () => void;
}

function findStep(plan: StudyPlan | null, stepId: string): PlanStep | null {
  if (!plan) return null;
  const steps = plan.stages?.length
    ? plan.stages.flatMap((stage) => stage.steps)
    : (plan.steps ?? []);
  return steps.find((s) => s.step_id === stepId) ?? null;
}

/** LearnPage：独立学习页（/courses/{courseId}/learn/{stepId}）。
 *
 * 职责边界（产品形态）：
 * - 学习地图 = 我应该怎么学 / 现在在哪 / 为什么推荐；
 * - 计划列表 = 学习顺序、时间、进度；
 * - 本页 = 真正学习知识内容（Rich Learning Document）。
 *
 * 进入本页即把 not_started 的 PlanStep 置为 in_progress（直接访问 URL / 刷新同样生效），
 * 「完成本节讲解」只更新 PlanStep completion，绝不修改 mastery。
 */
export function LearnPage() {
  const api = useApi();
  const nav = useLearningNav();
  const { courseId, stepId } = useParams<{ courseId: string; stepId: string }>();
  const { openMobileSidebar = () => {} } = useOutletContext<OutletCtx>() ?? {};

  const [course, setCourse] = useState<Course | null>(null);
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [planStatus, setPlanStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  // stale-async 保护：courseId / stepId / user 变化时，旧响应不许覆盖新页面
  const scopeSeq = useRef(0);
  // 「进入即 in_progress」只做一次，避免 plan 刷新触发重复 PATCH
  const startedRef = useRef<string>("");

  useEffect(() => {
    if (!courseId) return;
    const seq = ++scopeSeq.current;
    setCourse(null);
    setPlan(null);
    setPlanStatus("loading");
    setError("");
    api
      .getCourse(courseId)
      .then((c) => {
        if (seq === scopeSeq.current) setCourse(c);
      })
      .catch(() => {
        /* 课程标题失败不阻塞讲解本体 */
      });
    api
      .getPlan(courseId)
      .then((p) => {
        if (seq !== scopeSeq.current) return;
        if (!p) {
          setPlanStatus("error");
          setError("这门课程还没有学习计划");
          return;
        }
        setPlan(p);
        setPlanStatus("ready");
      })
      .catch(() => {
        if (seq !== scopeSeq.current) return;
        setPlanStatus("error");
        setError("无法加载学习计划，请重试");
      });
  }, [courseId, api]);

  const step = findStep(plan, stepId ?? "");

  // 进入讲解页即开始本节（not_started → in_progress）
  useEffect(() => {
    if (!courseId || !stepId || !step) return;
    if (step.status !== "not_started") return;
    const key = `${courseId}:${stepId}`;
    if (startedRef.current === key) return;
    startedRef.current = key;
    const seq = scopeSeq.current;
    api
      .updateStep(courseId, stepId, "in_progress")
      .then((p) => {
        if (seq === scopeSeq.current && p) setPlan(p);
      })
      .catch(() => {
        // 状态同步失败不阻塞阅读；下次进入会重试
        startedRef.current = "";
      });
  }, [courseId, stepId, step, api]);

  const requestExplanation = useCallback(
    async (targetStepId: string): Promise<StepExplanation> => {
      if (!courseId || !plan) throw new Error("no plan loaded");
      return api.getExplanation(courseId, plan.plan_id, targetStepId);
    },
    [courseId, api, plan]
  );

  // 完成本节讲解：只更新 PlanStep completion，绝不修改 mastery
  const completeStep = useCallback(
    async (targetStepId: string): Promise<boolean> => {
      if (!courseId) return false;
      const seq = scopeSeq.current;
      try {
        const p = await api.updateStep(courseId, targetStepId, "completed");
        if (seq !== scopeSeq.current) return false;
        if (p) setPlan(p);
        return true;
      } catch (e) {
        if (seq !== scopeSeq.current) return false;
        setError(e instanceof Error ? e.message : "更新失败");
        return false;
      }
    },
    [courseId, api]
  );

  const backToMap = useCallback(() => {
    if (courseId) nav.openCoursePlan(courseId);
  }, [courseId, nav]);

  if (!courseId || !stepId) {
    return (
      <>
        <CourseHeader course={null} activeView="plan" onOpenMobileSidebar={openMobileSidebar} />
        <div className="plan-scroll">
          <div className="plan-doc">
            <div className="inline-error" role="alert">
              讲解地址无效
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <CourseHeader course={course} activeView="plan" onOpenMobileSidebar={openMobileSidebar} />
      <div className="plan-scroll">
        <div className="plan-doc learn-doc">
          {/* 顶部固定返回入口：讲解页永远能回到学习地图 */}
          <div className="learn-topbar">
            <button type="button" className="learn-back-btn" onClick={backToMap}>
              <ArrowLeft size={15} aria-hidden /> 返回学习地图
            </button>
            {step && (
              <button
                type="button"
                className="step-ask-btn"
                onClick={() => nav.openCourseChat(courseId, { stepId })}
              >
                <MessageCircleQuestion size={14} aria-hidden /> 就此提问
              </button>
            )}
          </div>

          {planStatus === "loading" && (
            <div className="explanation-loading" aria-busy="true">
              <LoaderCircle size={15} className="spin" aria-hidden /> 正在打开学习内容…
            </div>
          )}

          {planStatus === "error" && (
            <div className="inline-error" role="alert">
              {error || "无法加载学习内容"}
            </div>
          )}

          {planStatus === "ready" && !step && (
            <div className="learn-missing">
              <h2>找不到这个学习内容</h2>
              <p>这个知识点可能已随计划重新生成而变化，请回到学习地图重新选择。</p>
              <button type="button" className="ea-button primary" onClick={backToMap}>
                返回学习地图
              </button>
            </div>
          )}

          {planStatus === "ready" && step && (
            <ExplanationDocument
              key={`${courseId}:${stepId}`}
              stepId={stepId}
              kcId={step.kc_id}
              stageTitle={step.stage_title}
              onRequestExplanation={requestExplanation}
              onCompleteStep={completeStep}
              alreadyCompleted={step.status === "completed"}
            />
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
