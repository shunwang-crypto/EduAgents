import type { ExplanationBlock } from "../../../api/types";

/** 单个结构化讲解 block 的渲染（不同 type 使用不同 UI，见 §26-35）。 */
export default function ExplanationBlockView({ block }: { block: ExplanationBlock }) {
  switch (block.type) {
    case "big_picture":
      return <BigPicture block={block} />;
    case "code_walkthrough":
      return <CodeWalkthrough block={block} />;
    case "recap":
      return <Recap block={block} />;
    case "handoff":
      return <Handoff block={block} />;
    case "contrast":
      return <Contrast block={block} />;
    default:
      return <PlainBlock block={block} />;
  }
}

function PlainBlock({ block }: { block: ExplanationBlock }) {
  const steps = Array.isArray(block.data?.steps) ? (block.data.steps as string[]) : [];
  return (
    <div className="exp-block exp-block-plain">
      {block.content && <p className="exp-content">{block.content}</p>}
      {steps.length > 0 && (
        <ol className="exp-steps">
          {steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

function BigPicture({ block }: { block: ExplanationBlock }) {
  const items = (block.data?.items as string[] | undefined) ?? [];
  const nodes = (block.data?.nodes as string[] | undefined) ?? [];
  const content = block.content;
  const hasFlow = items.length > 0 || nodes.length > 0;
  return (
    <div className="exp-block exp-big-picture">
      {content && <p className="exp-content">{content}</p>}
      {hasFlow && (
        <div className="exp-flow">
          {(items.length ? items : nodes).map((it, i, arr) => (
            <span key={i} className="exp-flow-item">
              {it}
              {i < arr.length - 1 && <span className="exp-flow-arrow">→</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function CodeWalkthrough({ block }: { block: ExplanationBlock }) {
  const code = (block.data?.code as string | undefined) ?? block.content;
  const annotations = (block.data?.annotations as Array<{ line: number; label: string; explanation: string }> | undefined) ?? [];
  return (
    <div className="exp-block exp-code">
      {block.content && !code && <p className="exp-content">{block.content}</p>}
      {code && <pre className="exp-code-block"><code>{code}</code></pre>}
      {annotations.length > 0 && (
        <ul className="exp-annotations">
          {annotations.map((a, i) => (
            <li key={i} className="exp-annotation">
              <span className="exp-annotation-label">L{a.line} · {a.label}</span>
              <span className="exp-annotation-text">{a.explanation}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Recap({ block }: { block: ExplanationBlock }) {
  const points = (block.data?.points as string[] | undefined) ?? [];
  return (
    <div className="exp-block exp-recap">
      {points.length > 0 ? (
        <ol className="exp-recap-points">
          {points.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ol>
      ) : (
        <p className="exp-content">{block.content}</p>
      )}
    </div>
  );
}

function Handoff({ block }: { block: ExplanationBlock }) {
  return (
    <div className="exp-block exp-handoff">
      <p className="exp-content">{block.content}</p>
    </div>
  );
}

function Contrast({ block }: { block: ExplanationBlock }) {
  const steps = Array.isArray(block.data?.steps) ? (block.data.steps as string[]) : [];
  return (
    <div className="exp-block exp-contrast">
      {block.content && <p className="exp-content">{block.content}</p>}
      {steps.length > 0 && (
        <ul className="exp-contrast-list">
          {steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
