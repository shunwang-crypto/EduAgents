/** 推荐原因（ReasonCode）→ 人类可读文本（§15）。覆盖后端全部 ReasonCode。 */

const REASON_CODE_LABELS: Record<string, string> = {
  UNKNOWN_STATE: "这个知识点尚未评估",
  LOW_MASTERY: "当前掌握度仍需加强",
  MISCONCEPTION_DETECTED: "已有学习记录显示这里可能存在理解偏差",
  PREREQUISITE_FOR_GOAL: "它是后续目标能力的重要基础",
  PREREQUISITE_NOT_MET: "部分前置知识尚未满足",
  PREREQUISITE_SATISFIED: "前置条件已经满足",
  RECENT_ERROR: "最近的学习记录显示这里仍需加强",
  RECENT_SUCCESS: "最近的学习表现较好",
  GOAL_RELEVANT: "它与你的学习目标直接相关",
  NEXT_IN_PLAN: "它位于当前建议学习顺序中",
  MASTERY_THRESHOLD_REACHED: "已经达到当前掌握标准",
  REVIEW_REQUIRED: "建议适当复习巩固",
  IS_GOAL: "它是课程的学习目标",
};

/** 后端 ReasonCode 全集（与后端 ReasonCode enum 对齐；用于契约测试）。 */
export const REASON_CODES = [
  "UNKNOWN_STATE",
  "LOW_MASTERY",
  "MISCONCEPTION_DETECTED",
  "PREREQUISITE_FOR_GOAL",
  "PREREQUISITE_NOT_MET",
  "PREREQUISITE_SATISFIED",
  "RECENT_ERROR",
  "RECENT_SUCCESS",
  "GOAL_RELEVANT",
  "NEXT_IN_PLAN",
  "MASTERY_THRESHOLD_REACHED",
  "REVIEW_REQUIRED",
];

export function reasonCodeToHuman(code: string): string {
  return REASON_CODE_LABELS[code] ?? "系统根据当前学习路径推荐";
}
