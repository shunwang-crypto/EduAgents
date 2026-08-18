import { useCallback, useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { StepExplanation } from "../../../api/types";
import ExplanationBlockView from "./ExplanationBlockView";

interface Props {
  stepId: string;
  kcId: string;
  onRequestExplanation: (stepId: string, kcId: string) => Promise<StepExplanation>;
  onBackToMap?: () => void;
  onPracticeHandoff?: () => void;
}

/**
 * Structured Explanation Workspace（§10/§67）。
 * 不是 Chat、不是 Markdown 长文：结构化分块 + 上一部分/下一部分导航。
 */
export default function ExplanationWorkspace({
  stepId,
  kcId,
  onRequestExplanation,
  onBackToMap,
  onPracticeHandoff,
}: Props) {
  const [explanation, setExplanation] = useState<StepExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setExplanation(null);
    setIndex(0);
    setError(null);
    if (!stepId) return;
    let cancelled = false;
    setLoading(true);
    onRequestExplanation(stepId, kcId)
      .then((exp) => {
        if (cancelled) return;
        setExplanation(exp);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "讲解加载失败");
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
  const current = blocks[index];

  const goPrev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);
  const goNext = useCallback(() => setIndex((i) => Math.min(blocks.length - 1, i + 1)), [blocks.length]);

  if (!stepId) {
    return (
      <div className="explanation-workspace explanation-workspace-empty">
        点击计划步骤的「查看讲解」，或在地图中选择一个知识组件。
      </div>
    );
  }

  return (
    <div className="explanation-workspace">
      <div className="explanation-header">
        <div>
          <div className="explanation-title">{explanation?.title ?? "结构化讲解"}</div>
          {explanation?.objective && (
            <div className="explanation-objective">{explanation.objective}</div>
          )}
        </div>
        {onBackToMap && (
          <button type="button" className="ea-button" onClick={onBackToMap}>
            查看知识地图
          </button>
        )}
      </div>

      {loading && (
        <div className="explanation-loading" aria-busy="true">
          <LoaderCircle size={15} className="spin" aria-hidden /> 正在生成讲解…
        </div>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button type="button" className="ea-button" onClick={() => setError("")}>
            关闭
          </button>
        </div>
      )}
      {!loading && !error && explanation && blocks.length > 0 && current && (
        <>
          {/* 目录式跳转（§68，不是聊天时间轴） */}
          <div className="explanation-nav-dots">
            {blocks.map((b, i) => (
              <button
                key={i}
                type="button"
                title={b.title}
                className={`explanation-dot ${i === index ? "active" : ""}`}
                onClick={() => setIndex(i)}
              >
                <span className="explanation-dot-dot" />
                <span className="explanation-dot-title">{b.title}</span>
              </button>
            ))}
          </div>

          <div className="explanation-step-head">
            <span className="explanation-step-count">
              第 {index + 1} / {blocks.length} 部分
            </span>
            <h3 className="explanation-block-title">{current.title}</h3>
          </div>
          <ExplanationBlockView block={current} />

          <div className="explanation-nav">
            <button type="button" className="ea-button" onClick={goPrev} disabled={index === 0}>
              上一部分
            </button>
            <div className="explanation-nav-spacer" />
            {index < blocks.length - 1 ? (
              <button type="button" className="ea-button primary" onClick={goNext}>
                下一部分
              </button>
            ) : (
              onPracticeHandoff && (
                <button type="button" className="ea-button primary" onClick={onPracticeHandoff}>
                  进入相关实践
                </button>
              )
            )}
          </div>
        </>
      )}
      {!loading && !error && explanation && blocks.length === 0 && (
        <div className="explanation-empty">暂无讲解内容</div>
      )}
    </div>
  );
}
