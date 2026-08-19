/** 知识点状态 → 人类可读文本 + 系统推荐动作（§14/§31）。 */

import type { KCStatus } from "../../../api/types";

export const STATUS_LABELS: Record<KCStatus, string> = {
  unknown: "尚待评估",
  weak: "薄弱",
  learning: "学习中",
  mastered: "已掌握",
};

export const STATUS_GLYPH: Record<KCStatus, string> = {
  unknown: "?",
  weak: "△",
  learning: "◐",
  mastered: "✓",
};

export interface RecommendationCopy {
  title: string;
  /** 建议动作文案；action=undefined 表示无明确动作（如已掌握/锁定）。 */
  detail: string;
}

/**
 * 系统推荐动作（§14）——必须显式判断 status，禁止用 !recommended 推导“已掌握”。
 * locked 优先于 status。
 */
export function recommendationCopy(
  node: { locked: boolean; status: KCStatus; recommended: boolean },
): RecommendationCopy {
  if (node.locked) return { title: "建议先完成前置知识", detail: "该知识点暂未解锁" };
  if (node.status === "mastered") return { title: "已掌握，可按需复习", detail: "掌握度已达标" };
  if (node.recommended) return { title: "建议现在学习", detail: "当前推荐" };
  if (node.status === "learning") return { title: "可以继续学习", detail: "正在学习中" };
  if (node.status === "weak") return { title: "建议继续巩固", detail: "掌握度仍需加强" };
  // unknown + unlocked + not recommended → 可以学习，但非首要推荐
  return { title: "可以学习", detail: "当前不是首要推荐" };
}
