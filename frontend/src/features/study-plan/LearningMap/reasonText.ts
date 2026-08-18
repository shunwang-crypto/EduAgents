/** Reason Codes → 人话（§24）。开发模式可保留英文，但 UI 主文案必须可读。 */

export const REASON_CODE_LABELS: Record<string, string> = {
  LOW_MASTERY: "当前掌握度较低",
  PREREQUISITE_FOR_GOAL: "它是达成目标的前置知识",
  RECENT_ERROR: "最近练习出现错误",
  RECENT_SUCCESS: "最近回答正确",
  MISCONCEPTION_DETECTED: "检测到理解误区",
  IS_GOAL: "是课程目标知识点",
  UNKNOWN: "尚未评估",
  PREREQUISITE_MET: "前置知识已满足",
};

export function reasonCodeToHuman(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}
