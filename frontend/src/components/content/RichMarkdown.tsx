import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "./RichMarkdown.css";

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
        {content}
      </ReactMarkdown>
    </div>
  );
}

/** 深色代码块 + 语言标签 + 复制按钮（结构先正确，不做复杂高亮）。 */
function CodeBlock(props: React.HTMLAttributes<HTMLPreElement>) {
  const [copied, setCopied] = React.useState(false);
  const children = React.Children.toArray(props.children) as React.ReactElement[];
  const codeEl = children.find((c) => React.isValidElement(c) && c.type === "code");
  const raw = React.Children.toArray(codeEl?.props?.children ?? [])
    .map((node) => (typeof node === "string" || typeof node === "number" ? String(node) : ""))
    .join("");
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
        <button type="button" className="md-copy-btn" onClick={copy} aria-label={copied ? "代码已复制" : "复制代码"}>
          {copied ? "已复制" : "复制"}
        </button>
        <span className="md-copy-live" role="status" aria-live="polite">{copied ? "已复制" : ""}</span>
      </div>
      <pre {...props}>{codeEl}</pre>
    </div>
  );
}
