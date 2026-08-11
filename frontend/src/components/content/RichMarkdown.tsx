import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "./RichMarkdown.css";

/**
 * 把模型产出的 \(...\) / \[...\] LaTeX 括法统一为 $...$ / $$...$$，
 * 供 remark-math + rehype-katex 正确解析。绝不修改 fenced code block 内内容。
 */
export function normalizeMarkdownMath(markdown: string): string {
  if (!markdown) return markdown;
  let result = "";
  let inFence = false;
  let fenceChar = "";
  let i = 0;
  const n = markdown.length;
  while (i < n) {
    const ch = markdown[i];
    // fenced code block：```` / ~~~ 开头行
    if (ch === "`" || ch === "~") {
      let run = 0;
      while (i + run < n && markdown[i + run] === ch) run += 1;
      if (!inFence && run >= 3 && (i === 0 || markdown[i - 1] === "\n")) {
        inFence = true;
        fenceChar = ch;
        result += markdown.slice(i, i + run);
        i += run;
        continue;
      }
      if (inFence && ch === fenceChar && run >= 3) {
        // 检查是否到闭合行尾
        let j = i + run;
        while (j < n && markdown[j] !== "\n") j += 1;
        if (j === n || /^\s*$/.test(markdown.slice(i + run, j))) {
          inFence = false;
        }
        result += markdown.slice(i, j);
        i = j;
        continue;
      }
      result += ch;
      i += 1;
      continue;
    }
    if (!inFence) {
      if (markdown.startsWith("\\[", i)) {
        result += "$$";
        i += 2;
        continue;
      }
      if (markdown.startsWith("\\]", i)) {
        result += "$$";
        i += 2;
        continue;
      }
      if (markdown.startsWith("\\(", i)) {
        result += "$";
        i += 2;
        continue;
      }
      if (markdown.startsWith("\\)", i)) {
        result += "$";
        i += 2;
        continue;
      }
    }
    result += ch;
    i += 1;
  }
  return result;
}

interface RichMarkdownProps {
  content: string;
}

export default function RichMarkdown({ content }: RichMarkdownProps) {
  return (
    <div className="rich-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: (props) => (
            <a {...props} target="_blank" rel="noopener noreferrer">
              {props.children}
            </a>
          ),
          table: (props) => (
            <div className="md-table-wrap">
              <table {...props} />
            </div>
          ),
          pre: (props) => <CodeBlock {...props} />,
        }}
      >
        {normalizeMarkdownMath(content)}
      </ReactMarkdown>
    </div>
  );
}

/** 深色代码块 + 语言标签 + 复制按钮（结构先正确，不做复杂高亮）。 */
function CodeBlock(props: React.HTMLAttributes<HTMLPreElement>) {
  const [copied, setCopied] = React.useState(false);
  const children = React.Children.toArray(props.children) as React.ReactElement[];
  const codeEl = children.find((c) => React.isValidElement(c) && c.type === "code");
  const raw = codeEl && typeof codeEl.props.children === "string" ? codeEl.props.children : "";
  const className = codeEl?.props?.className ?? "";
  const lang = typeof className === "string"
    ? className.replace(/^language-/, "")
    : "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(raw);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard 不可用时静默
    }
  };

  return (
    <div className="md-code-block">
      <div className="md-code-head">
        <span className="md-code-lang">{lang || "code"}</span>
        <button type="button" className="md-copy-btn" onClick={copy}>
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre {...props}>{codeEl}</pre>
    </div>
  );
}
