import { describe, expect, it } from "vitest";
import { buildExplanationToc } from "./ExplanationDocument";
import type { ExplanationBlock } from "../../../api/types";

function blocks(count: number): ExplanationBlock[] {
  return Array.from({ length: count }, (_, index) => ({
    type: index % 5 === 0 ? "diagram" : "concept",
    title: index === 8 ? "最速上升原理" : `主题 ${index + 1}`,
    content: "正文",
    data: {},
    source_refs: [],
  } as ExplanationBlock));
}

describe("buildExplanationToc", () => {
  it("keeps short explanations one item per rendered block", () => {
    const toc = buildExplanationToc(blocks(5));
    expect(toc.map((item) => item.blockIndex)).toEqual([0, 1, 2, 3, 4]);
  });

  it("compresses long explanations to 6-12 ordered topic anchors", () => {
    const toc = buildExplanationToc(blocks(24));
    expect(toc.length).toBeGreaterThanOrEqual(6);
    expect(toc.length).toBeLessThanOrEqual(12);
    expect(toc.map((item) => item.blockIndex)).toEqual(
      [...toc].map((item) => item.blockIndex).sort((a, b) => a - b)
    );
  });

  it("deduplicates repeated semantic titles without dropping body blocks", () => {
    const input = blocks(5);
    input[0].title = "最速上升原理";
    input[3].title = "最速上升原理";
    const toc = buildExplanationToc(input);
    expect(toc.filter((item) => item.title === "最速上升原理")).toHaveLength(1);
    expect(toc.length).toBe(4);
  });
});
