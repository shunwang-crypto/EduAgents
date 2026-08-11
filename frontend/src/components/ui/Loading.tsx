import { LoaderCircle } from "lucide-react";

/** 3-dot thinking indicator（克制的小灰点动画）。 */
export function LoadingDots() {
  return (
    <span className="loading-dots" role="status" aria-live="polite" aria-label="正在思考">
      <span className="loading-dot" />
      <span className="loading-dot" />
      <span className="loading-dot" />
    </span>
  );
}

/** 生成中按钮态（LoaderCircle + 文案）。 */
export function LoadingButton({ label }: { label: string }) {
  return (
    <span className="loading-btn">
      <LoaderCircle size={14} className="spin" aria-hidden />
      {label}
    </span>
  );
}
