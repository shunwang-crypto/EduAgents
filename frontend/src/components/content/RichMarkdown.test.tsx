import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import RichMarkdown from "./RichMarkdown";

/** RichMarkdown 行为测试（不依赖手写 lexer；remark-math 原生处理 $ / $$）。 */
function renderMd(md: string) {
  return render(<RichMarkdown content={md} />);
}

describe("RichMarkdown", () => {
  beforeEach(() => {
    // jsdom 无 clipboard：mock 掉复制
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("renders bold", () => {
    renderMd("你好 **加粗** 世界");
    expect(screen.getByText("加粗").tagName).toBe("STRONG");
  });

  it("renders GFM table", () => {
    renderMd("| a | b |\n| --- | --- |\n| 1 | 2 |");
    expect(document.querySelector(".md-table-wrap table")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("renders inline math $x$", () => {
    renderMd("公式 $E=mc^2$ 结束");
    expect(document.querySelector(".katex")).toBeTruthy();
  });

  it("renders display math $$...$$", () => {
    renderMd("$$\n\\operatorname{Attention}(Q,K,V)\n$$");
    expect(document.querySelector(".katex-display")).toBeTruthy();
  });

  it("renders fenced python code with copy button", async () => {
    renderMd("```python\nprint(1)\n```");
    const copyBtn = await screen.findByRole("button", { name: /复制代码/ });
    expect(copyBtn).toBeTruthy();
    expect(document.querySelector(".md-code-lang")?.textContent).toBe("python");
  });

  it("keeps \\(x\\) inside fenced code raw (no math transform)", () => {
    renderMd("```\n\\(x\\)\n```");
    // lexer 已删除：fenced code 内原样文本，katex 不解析
    expect(document.querySelector(".katex")).toBeNull();
    expect(document.querySelector("code")?.textContent).toContain("\\(");
  });

  it("keeps `\\(x\\)` inside inline code raw", () => {
    renderMd("示例：`\\(x\\)` 是代码文本");
    expect(document.querySelector(".katex")).toBeNull();
    expect(document.querySelector("code")?.textContent).toContain("\\(");
  });

  it("keeps \\[x\\] inside tilde fence raw", () => {
    renderMd("~~~\n\\[x\\]\n~~~");
    expect(document.querySelector(".katex")).toBeNull();
    expect(document.querySelector("code")?.textContent).toContain("\\[");
  });

  it("does not execute raw HTML", () => {
    renderMd("<img src=x onerror='window.__hacked=1'>");
    expect((window as unknown as Record<string, unknown>).__hacked).toBeUndefined();
  });

  it("external links open in new tab safely", () => {
    renderMd("[文档](https://example.com)");
    const link = document.querySelector("a") as HTMLAnchorElement;
    expect(link?.target).toBe("_blank");
    expect(link?.rel).toContain("noopener");
    expect(link?.rel).toContain("noreferrer");
  });

  it("copy button copies full code", async () => {
    const userEvent = (await import("@testing-library/user-event")).default;
    renderMd("```js\nconst a = 1;\n```");
    const btn = await screen.findByRole("button", { name: /复制代码/ });
    await userEvent.click(btn);
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("const a = 1;\n")
    );
  });
});
