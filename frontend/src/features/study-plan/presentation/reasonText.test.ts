import { describe, it, expect } from "vitest";
import { reasonCodeToHuman, REASON_CODES } from "./reasonText";
import { recommendationCopy } from "./statusText";

describe("§89 ReasonCode 人类文案", () => {
  it("所有后端 reason code 都有中文文案，且不泄露 raw enum", () => {
    const rawEnums = new Set(REASON_CODES);
    for (const code of REASON_CODES) {
      const human = reasonCodeToHuman(code);
      expect(human.length).toBeGreaterThan(0);
      expect(human).not.toBe(code); // 不能原样返回 raw code
      expect(rawEnums.has(human)).toBe(false);
    }
  });

  it("未知 code 回退到通用文案", () => {
    expect(reasonCodeToHuman("SOME_UNKNOWN_CODE")).toBe("系统根据当前学习路径推荐");
  });
});

describe("§90 UNKNOWN 节点不显示 0% / 已掌握", () => {
  it("unknown + unlocked + 非当前推荐 → 可以学习，非首要推荐", () => {
    const copy = recommendationCopy({ locked: false, status: "unknown", recommended: false });
    expect(copy.title).toBe("可以学习");
    expect(copy.detail).toContain("不是首要推荐");
    expect(copy.title).not.toContain("已掌握");
  });

  it("mastered 才显示已掌握；推荐只能来自 recommended=true", () => {
    expect(recommendationCopy({ locked: false, status: "mastered", recommended: false }).title).toBe(
      "已掌握，可按需复习"
    );
    expect(recommendationCopy({ locked: false, status: "unknown", recommended: true }).title).toBe(
      "建议现在学习"
    );
  });
});
