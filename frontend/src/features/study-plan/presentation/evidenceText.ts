/** 学习记录（Evidence）类型 → 人类可读文本（§12）。 */

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  concept_question: "概念理解记录",
  coding_task: "编程实践记录",
  assessment: "学习评估",
  practice: "实践记录",
  tutor: "学习互动记录",
  tutor_turn: "学习互动记录",
};

/** 无法识别的类型 → 一律回退为通用“学习记录”，绝不显示内部 event type。 */
export function evidenceTypeToHuman(type: string): string {
  return EVIDENCE_TYPE_LABELS[type] ?? "学习记录";
}
