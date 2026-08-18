/** Learning Map 展示文本 helpers：掌握度格式化、UNKNOWN 语义等。 */

/** 掌握度：UNKNOWN(mastery=null) 必须显示「?」，绝不为 0%。 */
export function masteryText(mastery: number | null | undefined): string {
  if (mastery === null || mastery === undefined) return "?";
  return `${Math.round(mastery * 100)}%`;
}

/** 评估可信度：null → 「暂无足够依据」，绝不为「?」。 */
export function confidenceText(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return "暂无足够依据";
  return `${Math.round(confidence * 100)}%`;
}
