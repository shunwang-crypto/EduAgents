import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, LoaderCircle } from "lucide-react";
import type { PracticeHandoff, StepExplanation } from "../../../api/types";
import ExplanationBlockView from "./ExplanationBlockView";

export interface ExplanationTocItem {
  title: string;
  blockIndex: number;
}

function titleKey(title: string): string {
  return title
    .toLocaleLowerCase()
    .replace(/[\s\u3000()（）[\]【】{}「」:：,，.!！？?、\-—_·]+/g, "")
    .replace(/^(章节|第[一二三四五六七八九十百0-9]+节)/, "");
}

/**
 * Long explanations contain many teaching blocks, but the left rail should
 * expose themes rather than every paragraph-sized block. The first block of
 * each theme remains the scroll target; all blocks still render in the body.
 */
export function buildExplanationToc(blocks: StepExplanation["blocks"]): ExplanationTocItem[] {
  if (blocks.length <= 12) {
    const seen = new Set<string>();
    return blocks.flatMap((block, blockIndex) => {
      const key = titleKey(block.title);
      if (!key || seen.has(key)) return [];
      seen.add(key);
      return [{ title: block.title, blockIndex }];
    });
  }

  const candidates: ExplanationTocItem[] = [];
  const seen = new Set<string>();
  let lastAnchor = -1;
  blocks.forEach((block, blockIndex) => {
    const key = titleKey(block.title);
    if (!key || seen.has(key)) return;
    const nonConcept = block.type !== "concept";
    const startsTheme = blockIndex === 0 || blockIndex - lastAnchor >= 3 || nonConcept;
    if (!startsTheme) return;
    seen.add(key);
    candidates.push({ title: block.title, blockIndex });
    lastAnchor = blockIndex;
  });

  if (candidates.length < 6) {
    const used = new Set(candidates.map((item) => item.blockIndex));
    for (let i = 0; i < 6; i += 1) {
      const blockIndex = Math.round((i * (blocks.length - 1)) / 5);
      if (!used.has(blockIndex)) {
        candidates.push({ title: blocks[blockIndex].title, blockIndex });
        used.add(blockIndex);
      }
    }
    candidates.sort((a, b) => a.blockIndex - b.blockIndex);
  }
  if (candidates.length <= 12) return candidates;
  const targetCount = Math.min(12, Math.max(6, Math.ceil(blocks.length / 3)));
  const selected: ExplanationTocItem[] = [];
  const used = new Set<number>();
  for (let i = 0; i < targetCount; i += 1) {
    const sourceIndex = Math.round((i * (candidates.length - 1)) / (targetCount - 1));
    const item = candidates[sourceIndex];
    if (item && !used.has(item.blockIndex)) {
      selected.push(item);
      used.add(item.blockIndex);
    }
  }
  return selected.sort((a, b) => a.blockIndex - b.blockIndex);
}

interface Props {
  stepId: string;
  kcId: string;
  /** 所属阶段名（面包屑用）。 */
  stageTitle?: string;
  onRequestExplanation: (stepId: string, kcId: string) => Promise<StepExplanation>;
  /** 完成本节讲解 → 只更新 PlanStep completion（不修改 mastery）。 */
  onCompleteStep?: (stepId: string) => Promise<boolean>;
  /** 完成本节后的下一步导航；没有后续 step 时由调用方回到学习地图。 */
  onContinueNext?: () => void;
  continueLabel?: string;
  /** 仅请求外部实践模块的 handoff 契约，不在讲解页生成练习。 */
  onRequestPractice?: () => Promise<PracticeHandoff | null>;
  /** 该 step 是否已经完成过（再次查看时按钮直接显示已完成）。 */
  alreadyCompleted?: boolean;
}

function readingMinutes(exp: StepExplanation | null): number {
  if (!exp) return 0;
  if (exp.estimated_minutes) return exp.estimated_minutes;
  // 后端未给预估时长时按正文字数估算（中文 ~400 字/分钟）
  const chars = exp.blocks.reduce(
    (sum, b) => sum + (b.content?.length ?? 0) + JSON.stringify(b.data ?? {}).length,
    0
  );
  return Math.max(1, Math.round(chars / 400));
}

/** Rich Learning Document：长文档 + 目录导航 + 自然滚动。
 *
 * 不做卡片翻页（没有「第 1/7 部分 → 下一部分」）：正文一次性完整渲染，
 * 目录只负责定位。篇幅由知识点复杂度决定，本组件不对内容做任何裁剪。
 */
export default function ExplanationDocument({
  stepId,
  kcId,
  stageTitle,
  onRequestExplanation,
  onCompleteStep,
  onContinueNext,
  continueLabel = "继续下一知识点",
  onRequestPractice,
  alreadyCompleted = false,
}: Props) {
  const [explanation, setExplanation] = useState<StepExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [completing, setCompleting] = useState(false);
  const [completed, setCompleted] = useState(alreadyCompleted);
  const [showHandoffNotice, setShowHandoffNotice] = useState(false);
  const [handoff, setHandoff] = useState<PracticeHandoff | null>(null);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const [practiceError, setPracticeError] = useState<string | null>(null);
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);

  useEffect(() => setCompleted(alreadyCompleted), [alreadyCompleted]);

  useEffect(() => {
    setExplanation(null);
    setActiveIndex(0);
    setError(null);
    setShowHandoffNotice(false);
    setHandoff(null);
    setPracticeError(null);
    if (!stepId) return;
    let cancelled = false;
    setLoading(true);
    onRequestExplanation(stepId, kcId)
      .then((exp) => {
        if (!cancelled) setExplanation(exp);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "讲解加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId, kcId]);

  const blocks = explanation?.blocks ?? [];
  const tocItems = useMemo(() => buildExplanationToc(blocks), [blocks]);

  // 目录点击 → 滚动到对应 section（自然滚动，不切页）
  const scrollToSection = useCallback(
    (index: number) => {
      const bounded = Math.max(0, Math.min(blocks.length - 1, index));
      sectionRefs.current[bounded]?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    },
    [blocks.length]
  );

  // 滚动时高亮当前所在 section（目录只反映位置，不驱动内容显示）
  useEffect(() => {
    if (!blocks.length || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!visible) return;
        const next = Number((visible.target as HTMLElement).dataset.sectionIndex);
        if (Number.isFinite(next)) {
          const tocIndex = tocItems.findIndex((item, index) => {
            const nextItem = tocItems[index + 1];
            return item.blockIndex <= next && (!nextItem || nextItem.blockIndex > next);
          });
          if (tocIndex >= 0) setActiveIndex(tocIndex);
        }
      },
      { rootMargin: "-12% 0px -70% 0px", threshold: 0.01 }
    );
    sectionRefs.current.forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, [blocks.length, tocItems]);

  const handleComplete = useCallback(async () => {
    if (!onCompleteStep || completing || completed) return;
    setCompleting(true);
    try {
      const ok = await onCompleteStep(stepId);
      if (ok) setCompleted(true);
    } finally {
      setCompleting(false);
    }
  }, [onCompleteStep, stepId, completing, completed]);

  const minutes = useMemo(() => readingMinutes(explanation), [explanation]);

  const handlePractice = useCallback(async () => {
    if (practiceLoading) return;
    setPracticeLoading(true);
    setPracticeError(null);
    try {
      const result = onRequestPractice ? await onRequestPractice() : null;
      setHandoff(result);
      setShowHandoffNotice(true);
    } catch (e) {
      setPracticeError(e instanceof Error ? e.message : "实践入口暂时不可用");
      setShowHandoffNotice(true);
    } finally {
      setPracticeLoading(false);
    }
  }, [onRequestPractice, practiceLoading]);

  if (!stepId) {
    return (
      <div className="explanation-document-empty">选择一个知识点查看学习讲解。</div>
    );
  }

  return (
    <article className="explanation-doc-root">
      <header className="explanation-header">
        <div className="explanation-headline">
          {stageTitle && <div className="explanation-kicker">{stageTitle}</div>}
          <h1 className="explanation-title">{explanation?.title ?? "学习讲解"}</h1>
          {explanation?.objective && (
            <p className="explanation-objective">{explanation.objective}</p>
          )}
          {explanation && blocks.length > 0 && (
            <div className="explanation-reading-meta">
            共 {tocItems.length} 节 · 预计阅读 {minutes} 分钟
            </div>
          )}
        </div>
        {completed && (
          <span className="explanation-done-badge">
            <CheckCircle2 size={15} aria-hidden /> 已完成
          </span>
        )}
      </header>

      {loading && (
        <div className="explanation-loading" aria-busy="true">
          <LoaderCircle size={15} className="spin" aria-hidden /> 正在准备学习内容…
        </div>
      )}

      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}

      {!loading && !error && explanation && blocks.length > 0 && (
        <div className="explanation-reading-layout">
          <nav className="explanation-toc" aria-label="讲解目录">
            <div className="explanation-toc-title">目录</div>
            {tocItems.map((item, i) => (
              <button
                key={`${item.blockIndex}-${i}`}
                type="button"
                className={`explanation-toc-item ${i === activeIndex ? "active" : ""}`}
                onClick={() => {
                  setActiveIndex(i);
                  scrollToSection(item.blockIndex);
                }}
                aria-current={i === activeIndex ? "location" : undefined}
              >
                <span>{String(i + 1).padStart(2, "0")}</span>
                {item.title}
              </button>
            ))}
          </nav>

          <div className="explanation-document">
            {blocks.map((block, i) => (
              <section
                key={`${block.type}-${i}`}
                ref={(node) => {
                  sectionRefs.current[i] = node;
                }}
                data-section-index={i}
                className="explanation-block-section"
                aria-labelledby={`exp-section-${i}`}
              >
                <h2 className="explanation-block-title" id={`exp-section-${i}`}>
                  {block.title}
                </h2>
                <ExplanationBlockView block={block} />
                {block.source_refs?.length ? (
                  <div className="explanation-sources">
                    资料来源：{block.source_refs.join(" · ")}
                  </div>
                ) : null}
              </section>
            ))}

            {/* 底部动作互不替代：完成只改 PlanStep，下一节按 StudyPlan 导航，实践走 handoff。 */}
            <footer className="explanation-footer-actions">
              {onCompleteStep && (
                <button
                  type="button"
                  className="ea-button primary"
                  onClick={() => void handleComplete()}
                  disabled={completing || completed}
                >
                  {completed ? "本节讲解已完成" : completing ? "正在完成…" : "完成本节讲解"}
                </button>
              )}
              {onContinueNext && (
                <button
                  type="button"
                  className="ea-button secondary"
                  onClick={onContinueNext}
                >
                  {continueLabel}
                </button>
              )}
              <button
                type="button"
                className="ea-button secondary"
                onClick={() => void handlePractice()}
                disabled={practiceLoading}
              >
                {practiceLoading ? "正在准备实践…" : "进入相关实践"}
              </button>
            </footer>
            <p className="explanation-footer-hint">
              完成讲解只记录学习进度；掌握度由后续实践与学习记录决定。
            </p>

            {showHandoffNotice && (
              <div className="handoff-notice" role="status">
                {practiceError ? (
                  <p>{practiceError}</p>
                ) : handoff ? (
                  <p>
                    已准备好实践入口（难度：{handoff.recommended_difficulty || "自适应"}）。
                    <br />
                    <small>实践模块会独立记录学习证据；本次操作不会修改掌握度。</small>
                  </p>
                ) : (
                  <p>
                    相关实践功能暂未开放。
                    <br />
                    <small>后续完成基础实践后，系统会根据学习记录更新你的知识掌握度。</small>
                  </p>
                )}
                <button
                  type="button"
                  className="ea-button"
                  onClick={() => setShowHandoffNotice(false)}
                >
                  关闭
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !error && explanation && blocks.length === 0 && (
        <div className="explanation-empty">暂无讲解内容</div>
      )}
    </article>
  );
}
