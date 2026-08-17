/** KC 状态 / 推荐 / 锁定的视觉样式（颜色 + 标签，不止靠颜色区分）。 */

import type { KCStatus } from "../../../api/types";

export interface StatusStyle {
  label: string;
  color: string;
  bg: string;
  border: string;
  badge: string; // 显示用短标签
}

export const STATUS_STYLES: Record<KCStatus, StatusStyle> = {
  unknown: {
    label: "未评估",
    color: "#64748b",
    bg: "#f1f5f9",
    border: "#cbd5e1",
    badge: "?",
  },
  weak: {
    label: "薄弱",
    color: "#b45309",
    bg: "#fffbeb",
    border: "#fcd34d",
    badge: "弱",
  },
  learning: {
    label: "学习中",
    color: "#1d4ed8",
    bg: "#eff6ff",
    border: "#93c5fd",
    badge: "学",
  },
  mastered: {
    label: "已掌握",
    color: "#15803d",
    bg: "#f0fdf4",
    border: "#86efac",
    badge: "✓",
  },
};

export function masteryText(mastery: number | null): string {
  if (mastery === null || mastery === undefined) return "?";
  return `${Math.round(mastery * 100)}%`;
}

export function statusOf(node: {
  status: KCStatus;
  recommended?: boolean;
  locked?: boolean;
}): StatusStyle {
  return STATUS_STYLES[node.status];
}
