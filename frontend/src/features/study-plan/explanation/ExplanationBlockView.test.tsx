import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ExplanationBlockView from "./ExplanationBlockView";
import type { ExplanationBlock } from "../../../api/types";

function block(p: Partial<ExplanationBlock>): ExplanationBlock {
  return {
    type: "concept",
    title: "t",
    content: "",
    data: {},
    source_refs: [],
    ...p,
  } as ExplanationBlock;
}

describe("ExplanationBlockView §91 BigPicture", () => {
  it("items 渲染为 NumPy → PyTorch → Neural Network，不出现 → →", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "big_picture",
          data: { items: ["NumPy", "PyTorch", "Neural Network"] },
        })}
      />
    );
    const flow = screen.getByText(/NumPy/).closest(".exp-flow");
    expect(flow).toBeTruthy();
    const arrows = flow?.querySelectorAll(".exp-flow-arrow");
    expect(arrows?.length).toBe(2);
    // 不存在连续箭头（data 中不含 "→" 会被原样渲染为两项）
    expect(flow?.textContent).not.toContain("→ →");
  });
});

describe("ExplanationBlockView §92 CodeWalkthrough", () => {
  it("data.code 缺失时，中文说明作为普通文本，不放进 code block", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "code_walkthrough",
          content: "这是说明文本，不是代码",
          data: {},
        })}
      />
    );
    // 普通文本可见
    expect(screen.getByText("这是说明文本，不是代码")).toBeTruthy();
    // 不能有 code block
    expect(document.querySelector(".exp-code-block")).toBeNull();
  });

  it("data.code 存在时显示 code block", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "code_walkthrough",
          content: "解释",
          data: { code: "print(1)" },
        })}
      />
    );
    expect(document.querySelector(".exp-code-block")).toBeTruthy();
  });
});

describe("ExplanationBlockView adaptive rich blocks", () => {
  it("concept content supports Markdown tables and formulas", () => {
    render(<ExplanationBlockView block={block({ content: "| A | B |\n|---|---|\n| 1 | 2 |\n\n$$x^2$$" })} />);
    expect(document.querySelector("table")).toBeTruthy();
    expect(document.querySelector(".katex")).toBeTruthy();
  });

  it("renders structured diagram nodes and image blocks", () => {
    const { rerender } = render(<ExplanationBlockView block={block({ type: "diagram", data: { nodes: [{ id: "a", label: "输入" }, { id: "b", label: "输出" }], edges: [{ source: "a", target: "b" }] } })} />);
    expect(document.querySelectorAll(".exp-flow-node").length).toBe(2);
    rerender(<ExplanationBlockView block={block({ type: "image", title: "架构图", data: { url: "/course-assets/arch.png", alt: "系统架构" } })} />);
    expect(screen.getByAltText("系统架构")).toBeTruthy();
  });

  it("renders legacy ASCII trees in a non-wrapping pre fallback", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "diagram",
          content: "插入前后结构如下：\n\nroot\n └── 'a'\n      └── 'p'\n\n第二个 p 保留后继。",
        })}
      />
    );
    const tree = screen.getByLabelText("ASCII tree");
    expect(tree.tagName).toBe("PRE");
    expect(tree.classList.contains("exp-ascii-tree")).toBe(true);
    expect(tree.textContent).toContain("      └── 'p'");
    expect(screen.getByText("插入前后结构如下：")).toBeTruthy();
    expect(screen.getByText("第二个 p 保留后继。")).toBeTruthy();
  });

  // 图示优先结构化：按依赖分层成流程图，分支节点同层并排
  it("layers diagram nodes by dependency and keeps branches side by side", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "diagram",
          data: {
            nodes: [
              { id: "in", label: "输入" },
              { id: "l", label: "左分支" },
              { id: "r", label: "右分支" },
              { id: "out", label: "输出" },
            ],
            edges: [
              { source: "in", target: "l" },
              { source: "in", target: "r" },
              { source: "l", target: "out" },
              { source: "r", target: "out" },
            ],
          },
        })}
      />
    );
    // 输入 → (左分支 | 右分支) → 输出 共 3 层，中间层两个并排节点
    const layers = document.querySelectorAll(".exp-flow-layer");
    expect(layers.length).toBe(3);
    expect(layers[1].querySelectorAll(".exp-flow-node").length).toBe(2);
    expect(document.querySelectorAll(".exp-flow-node").length).toBe(4);
  });

  // 兼容 "a -> b: 标签" 字符串边；带标签的边额外列出，避免信息丢失
  it("parses arrow-string edges and lists labeled edges", () => {
    render(
      <ExplanationBlockView
        block={block({
          type: "diagram",
          data: { edges: ["查询 -> 检索: 向量相似度", "检索 -> 生成"] },
        })}
      />
    );
    expect(document.querySelectorAll(".exp-flow-node").length).toBe(3);
    const extra = document.querySelector(".exp-diagram-edges");
    expect(extra?.textContent).toContain("向量相似度");
  });

  // big_picture 带 edges 时也按流程图渲染（否则退化为轻量 chips）
  it("renders big_picture as flowchart only when edges exist", () => {
    const { rerender } = render(
      <ExplanationBlockView
        block={block({
          type: "big_picture",
          data: { nodes: ["取数", "清洗"], edges: [{ source: "取数", target: "清洗" }] },
        })}
      />
    );
    expect(document.querySelectorAll(".exp-flow-node").length).toBe(2);
    rerender(
      <ExplanationBlockView block={block({ type: "big_picture", data: { items: ["取数", "清洗"] } })} />
    );
    expect(document.querySelector(".exp-flowchart")).toBeNull();
    expect(document.querySelectorAll(".exp-flow-item").length).toBe(2);
  });
});
