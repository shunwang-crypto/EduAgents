import { AlertCircle } from "lucide-react";

/** InlineError：轻量错误提示（小红 icon + 文本 + 可选重试），不做大红块。 */
export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="inline-error" role="alert">
      <AlertCircle size={15} aria-hidden />
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="inline-error-retry" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
