import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LearningMapNode } from "../../../api/types";
import { REASON_CODES, reasonCodeToHuman } from "./reasonText";
import { evidenceTypeToHuman } from "./evidenceText";
import { recommendationCopy } from "./statusText";
import KnowledgeDetailPanel from "../LearningMap/KnowledgeDetailPanel";

// §55：后端全部 ReasonCode 都有 presentation mapping，且不返回 raw code
describe("ReasonCode presentation", () => {
  it("covers every backend reason code with human text", () => {
    expect(REASON_CODES.length).toBeGreaterThanOrEqual(12);
    for (const code of REASON_CODES) {
      const human = reasonCodeToHuman(code);
      // 人类文本，非 raw code
      expect(human).not.toBe(code);
      expect(human.length).toBeGreaterThan(0);
    }
  });

  it("unknown reason code falls back to a human sentence, not the raw code", () => {
    const human = reasonCodeToHuman("SOME_UNKNOWN_CODE");
    expect(human).toBe("系统根据当前学习路径推荐");
    expect(human).not.toContain("SOME_UNKNOWN_CODE");
  });
});

// §63：Evidence label —— 不渲染内部 event type
describe("Evidence labels", () => {
  it("maps known types to human labels", () => {
    expect(evidenceTypeToHuman("concept_question")).toBe("概念理解记录");
    expect(evidenceTypeToHuman("coding_task")).toBe("编程实践记录");
    expect(evidenceTypeToHuman("practice")).toBe("实践记录");
  });
  it("unknown type falls back to 学习记录, not raw type", () => {
    expect(evidenceTypeToHuman("weird_internal_type")).toBe("学习记录");
  });
});

// §14/§57：推荐动作状态分支
describe("recommendationCopy status branches", () => {
  const base = { locked: false, status: "unknown" as const, recommended: false };
  it("unknown unlocked not-recommended → 可以学习, not 已掌握", () => {
    expect(recommendationCopy(base).title).toBe("可以学习");
  });
  it("current recommended → 建议现在学习", () => {
    expect(recommendationCopy({ ...base, recommended: true }).title).toBe("建议现在学习");
  });
  it("mastered → 已掌握", () => {
    expect(recommendationCopy({ ...base, status: "mastered" }).title).toBe("已掌握，可按需复习");
  });
  it("locked → 建议先完成前置知识", () => {
    expect(recommendationCopy({ ...base, locked: true }).title).toBe("建议先完成前置知识");
  });
  it("weak → 建议继续巩固", () => {
    expect(recommendationCopy({ ...base, status: "weak" }).title).toBe("建议继续巩固");
  });
});

// §16/§54：KnowledgeDetailPanel 不泄露内部 ReasonCode / raw id
describe("KnowledgeDetailPanel presentation", () => {
  const allCodes: LearningMapNode = {
    id: "kc_x", name: "示例知识点", description: "desc",
    difficulty: "easy", mastery: null, confidence: null, status: "unknown",
    recommended: true, locked: false,
    prerequisites: [], misconceptions: [], recent_evidence: [],
    reason_codes: REASON_CODES,
  };
  const masteredNode: LearningMapNode = {
    ...allCodes, id: "kc_y", name: "已掌握点", status: "mastered", mastery: 0.9,
    confidence: 0.9, recommended: false,
  };

  it("renders reason codes as human text, never raw codes", () => {
    render(<KnowledgeDetailPanel node={allCodes} allNodes={[allCodes, masteredNode]} />);
    // raw codes 绝不出现
    for (const code of ["UNKNOWN_STATE", "GOAL_RELEVANT", "NEXT_IN_PLAN", "PREREQUISITE_"]) {
      expect(screen.queryByText(new RegExp(code))).toBeNull();
    }
    // 映射成的人类文本出现
    expect(screen.getByText("这个知识点尚未评估")).toBeTruthy();
    expect(screen.getByText("它与你的学习目标直接相关")).toBeTruthy();
    expect(screen.getByText("它位于当前建议学习顺序中")).toBeTruthy();
    expect(screen.getByText("部分前置知识尚未满足")).toBeTruthy();
  });

  it("unknown mastered 区分：unknown 显示 可以学习 文案", () => {
    render(<KnowledgeDetailPanel node={allCodes} allNodes={[allCodes, masteredNode]} />);
    expect(screen.getByText("建议现在学习")).toBeTruthy();
  });
});
