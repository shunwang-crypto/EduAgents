import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RichMarkdown, { normalizeMarkdownMath } from "./RichMarkdown";

describe("normalizeMarkdownMath", () => {
  it("converts \\(...\\) to $...$", () => {
    expect(normalizeMarkdownMath("行内 \\(E = mc^2\\) 公式")).toContain("$E = mc^2$");
  });

  it("converts \\[...\\] to $$...$$", () => {
    expect(normalizeMarkdownMath("块级 \\[x^2 + y^2\\] 公式")).toContain("$$x^2 + y^2$$");
  });

  it("does not touch fenced code block content", () => {
    const md = "```python\n# \\( not math \\)\nprint(1)\n```";
    const out = normalizeMarkdownMath(md);
    expect(out).toContain("\\(");
    expect(out).toContain("\\)");
  });

  it("leaves plain text unchanged", () => {
    const md = "你好 **加粗** 世界";
    expect(normalizeMarkdownMath(md)).toBe(md);
  });
});

describe("RichMarkdown", () => {
  it("renders bold text", () => {
    render(<RichMarkdown content={"**重点**内容"} />);
    const strong = document.querySelector("strong");
    expect(strong?.textContent).toBe("重点");
  });

  it("renders markdown table", () => {
    render(
      <RichMarkdown
        content={"| a | b |\n| -- | -- |\n| 1 | 2 |"}
      />
    );
    const table = document.querySelector("table");
    expect(table).toBeTruthy();
    expect(table?.textContent).toContain("1");
    expect(table?.textContent).toContain("2");
  });

  it("renders inline math with katex", () => {
    render(<RichMarkdown content={"公式 $E = mc^2$ 很好"} />);
    const math = document.querySelector(".katex");
    expect(math).toBeTruthy();
  });

  it("renders display math with katex", () => {
    render(<RichMarkdown content={"$$\n\\frac{1}{2}\n$$"} />);
    const display = document.querySelector(".katex-display");
    expect(display).toBeTruthy();
  });

  it("renders fenced code block with language label", () => {
    render(
      <RichMarkdown content={"```python\nprint(1)\n```"} />
    );
    expect(document.querySelector(".md-code-lang")?.textContent).toBe("python");
    expect(document.querySelector("pre code")?.textContent).toContain("print(1)");
  });

  it("does not execute raw HTML (no dangerouslySetInnerHTML)", () => {
    render(<RichMarkdown content={'<img src="x" onerror="window.__xss=1">'} />);
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
    expect(document.querySelector("img[onerror]")).toBeNull();
  });

  it("renders links with target blank", () => {
    render(<RichMarkdown content={"[链接](https://example.com)"} />);
    const a = document.querySelector("a");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
  });
});
