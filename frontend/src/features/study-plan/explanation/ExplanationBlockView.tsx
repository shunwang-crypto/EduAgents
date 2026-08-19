import type { ExplanationBlock } from "../../../api/types";
import RichMarkdown from "../../../components/content/RichMarkdown";

/** 单个结构化讲解 block 的渲染（不同 type 使用不同 UI，见 §26-35）。 */
export default function ExplanationBlockView({ block }: { block: ExplanationBlock }) {
  switch (block.type) {
    // 整体模型带 edges 时按流程图渲染，否则用轻量 chips
    case "big_picture":
      return Array.isArray(block.data?.edges) && block.data.edges.length > 0 ? (
        <Diagram block={block} />
      ) : (
        <BigPicture block={block} />
      );
    case "diagram": return <Diagram block={block} />;
    case "image": return <ImageBlock block={block} />;
    case "table": return <TableBlock block={block} />;
    case "formula": return <FormulaBlock block={block} />;
    case "code_walkthrough": return <CodeWalkthrough block={block} />;
    case "recap": return <Recap block={block} />;
    case "handoff": return <Handoff block={block} />;
    case "contrast": return <Contrast block={block} />;
    default: return <PlainBlock block={block} />;
  }
}

function MarkdownContent({ content }: { content?: string }) {
  if (!content?.trim()) return null;
  const ascii = splitAsciiTree(content);
  if (!ascii) return <RichMarkdown content={content} />;
  return (
    <>
      {ascii.before && <RichMarkdown content={ascii.before} />}
      <pre className="exp-ascii-tree" aria-label="ASCII tree"><code>{ascii.tree}</code></pre>
      {ascii.after && <RichMarkdown content={ascii.after} />}
    </>
  );
}

function splitAsciiTree(content: string): { before: string; tree: string; after: string } | null {
  const normalized = content.replace(/\\n/g, "\n");
  const lines = normalized.split("\n");
  const branchLine = /^\s*(?:[│ ]*[├└]──)/;
  const firstBranch = lines.findIndex((line) => branchLine.test(line));
  if (firstBranch < 0) return null;
  let start = firstBranch;
  if (firstBranch > 0 && /^\s*root\b/i.test(lines[firstBranch - 1])) start = firstBranch - 1;
  let end = firstBranch;
  while (end + 1 < lines.length && branchLine.test(lines[end + 1])) end++;
  return {
    before: lines.slice(0, start).join("\n").trim(),
    tree: lines.slice(start, end + 1).join("\n"),
    after: lines.slice(end + 1).join("\n").trim(),
  };
}

function PlainBlock({ block }: { block: ExplanationBlock }) {
  const steps = Array.isArray(block.data?.steps) ? (block.data.steps as string[]) : [];
  return (
    <div className="exp-block exp-block-plain">
      <MarkdownContent content={block.content} />
      {steps.length > 0 && (
        <ol className="exp-steps">
          {steps.map((s, i) => <li key={i}><RichMarkdown content={s} /></li>)}
        </ol>
      )}
    </div>
  );
}

function BigPicture({ block }: { block: ExplanationBlock }) {
  const rawItems = Array.isArray(block.data?.items) ? block.data.items : [];
  const rawNodes = Array.isArray(block.data?.nodes) ? block.data.nodes : [];
  const labelOf = (item: unknown) => {
    if (typeof item === "string" || typeof item === "number") return String(item);
    const value = item as { label?: string; title?: string; id?: string };
    return value?.label ?? value?.title ?? value?.id ?? "";
  };
  const items = rawItems.map(labelOf).filter(Boolean);
  const nodes = rawNodes.map(labelOf).filter(Boolean);
  const content = block.content;
  const hasFlow = items.length > 0 || nodes.length > 0;
  return (
    <div className="exp-block exp-big-picture">
      <MarkdownContent content={content} />
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

interface DiagramNode {
  id: string;
  label: string;
}
interface DiagramEdge {
  source: string;
  target: string;
  label: string;
}

/** 归一化 diagram/flowchart 数据：兼容 [str] / [{id,label}] / [{source,target,label}] / ["a->b"]。 */
function parseDiagram(block: ExplanationBlock): { nodes: DiagramNode[]; edges: DiagramEdge[] } {
  const rawNodes = Array.isArray(block.data?.nodes) ? block.data.nodes : [];
  const rawEdges = Array.isArray(block.data?.edges) ? block.data.edges : [];
  const nodes: DiagramNode[] = [];
  const seen = new Map<string, DiagramNode>();
  const put = (id: string, label?: string) => {
    const key = id.trim();
    if (!key) return;
    const existing = seen.get(key);
    if (existing) {
      if (label && existing.label === existing.id) existing.label = label;
      return;
    }
    const node = { id: key, label: (label ?? key).trim() || key };
    seen.set(key, node);
    nodes.push(node);
  };

  rawNodes.forEach((node, index) => {
    if (typeof node === "string" || typeof node === "number") {
      put(String(node), String(node));
      return;
    }
    const value = node as { id?: string; label?: string; title?: string; name?: string };
    const label = value.label ?? value.title ?? value.name ?? value.id ?? String(index);
    put(value.id ?? label ?? String(index), label);
  });

  const edges: DiagramEdge[] = [];
  rawEdges.forEach((edge) => {
    if (typeof edge === "string") {
      // "a -> b" / "a → b"（可带 ": label"）
      const [chain, label = ""] = edge.split(/[:：]/, 2);
      const parts = chain.split(/->|→|=>/).map((p) => p.trim()).filter(Boolean);
      for (let i = 0; i < parts.length - 1; i++) {
        put(parts[i]);
        put(parts[i + 1]);
        edges.push({ source: parts[i], target: parts[i + 1], label: label.trim() });
      }
      return;
    }
    if (Array.isArray(edge) && edge.length >= 2) {
      put(String(edge[0]));
      put(String(edge[1]));
      edges.push({ source: String(edge[0]), target: String(edge[1]), label: String(edge[2] ?? "") });
      return;
    }
    const value = edge as { source?: string; target?: string; from?: string; to?: string; label?: string };
    const source = value.source ?? value.from;
    const target = value.target ?? value.to;
    if (!source || !target) return;
    put(source);
    put(target);
    edges.push({ source, target, label: (value.label ?? "").trim() });
  });

  return { nodes, edges };
}

/** 按最长路径给节点分层（Kahn）；存在环或数据不完整时退化为声明顺序。 */
function layerize(nodes: DiagramNode[], edges: DiagramEdge[]): DiagramNode[][] {
  if (!nodes.length) return [];
  if (!edges.length) return [nodes];
  const indegree = new Map(nodes.map((n) => [n.id, 0]));
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    if (!indegree.has(e.source) || !indegree.has(e.target)) continue;
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1);
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  }
  const depth = new Map(nodes.map((n) => [n.id, 0]));
  const queue = nodes.filter((n) => (indegree.get(n.id) ?? 0) === 0).map((n) => n.id);
  let visited = 0;
  while (queue.length) {
    const id = queue.shift()!;
    visited++;
    for (const next of outgoing.get(id) ?? []) {
      depth.set(next, Math.max(depth.get(next) ?? 0, (depth.get(id) ?? 0) + 1));
      const left = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, left);
      if (left === 0) queue.push(next);
    }
  }
  // 有环 → 不做假的分层，按声明顺序单列展示
  if (visited !== nodes.length) return [nodes];
  const maxDepth = Math.max(...nodes.map((n) => depth.get(n.id) ?? 0));
  const layers: DiagramNode[][] = Array.from({ length: maxDepth + 1 }, () => []);
  for (const node of nodes) layers[depth.get(node.id) ?? 0].push(node);
  return layers.filter((layer) => layer.length > 0);
}

/** 结构化图示 / 流程图：按依赖分层渲染，分支与并行步骤如实呈现。 */
function Diagram({ block }: { block: ExplanationBlock }) {
  const steps = Array.isArray(block.data?.steps) ? (block.data.steps as string[]) : [];
  const { nodes, edges } = parseDiagram(block);
  const layers = layerize(nodes, edges);
  const layerOf = new Map<string, number>();
  layers.forEach((layer, i) => layer.forEach((n) => layerOf.set(n.id, i)));
  const labelOf = new Map(nodes.map((n) => [n.id, n.label]));
  // 相邻层之间的无标签边由布局本身表达；其余（跨层 / 分支回边 / 带标签）单独列出，避免信息丢失
  const extraEdges = edges.filter(
    (e) =>
      e.label ||
      (layerOf.get(e.target) ?? 0) - (layerOf.get(e.source) ?? 0) !== 1 ||
      layers.length === 1
  );

  return (
    <div className="exp-block exp-diagram">
      <MarkdownContent content={block.content} />
      {layers.length > 0 && (
        <div className="exp-flowchart" role="group" aria-label={block.title}>
          {layers.map((layer, i) => (
            <div className="exp-flow-layer" key={i}>
              <div className="exp-flow-row">
                {layer.map((node) => (
                  <div className="exp-flow-node" key={node.id}>
                    {node.label}
                  </div>
                ))}
              </div>
              {i < layers.length - 1 && (
                <div className="exp-flow-connector" aria-hidden>
                  ↓
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {extraEdges.length > 0 && (
        <ul className="exp-diagram-edges">
          {extraEdges.map((e, i) => (
            <li key={i}>
              {labelOf.get(e.source) ?? e.source}
              {e.label ? ` —${e.label}→ ` : " → "}
              {labelOf.get(e.target) ?? e.target}
            </li>
          ))}
        </ul>
      )}
      {steps.length > 0 && (
        <ol className="exp-steps">
          {steps.map((s, i) => (
            <li key={i}>
              <RichMarkdown content={s} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ImageBlock({ block }: { block: ExplanationBlock }) {
  const url = typeof block.data?.url === "string" ? block.data.url : typeof block.data?.src === "string" ? block.data.src : "";
  const alt = String(block.data?.alt ?? block.title);
  const caption = String(block.data?.caption ?? "");
  return <div className="exp-block exp-image"><MarkdownContent content={block.content} />{url && <figure><img src={url} alt={alt} loading="lazy" />{caption && <figcaption>{caption}</figcaption>}</figure>}</div>;
}

function TableBlock({ block }: { block: ExplanationBlock }) {
  const headers = Array.isArray(block.data?.headers) ? (block.data.headers as string[]) : [];
  const rows = Array.isArray(block.data?.rows) ? (block.data.rows as unknown[]).map((row) => Array.isArray(row) ? row.map(String) : [String(row)]) : [];
  return <div className="exp-block exp-table"><MarkdownContent content={block.content} />{headers.length > 0 && <div className="exp-table-wrap"><table><thead><tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}><RichMarkdown content={cell} /></td>)}</tr>)}</tbody></table></div>}</div>;
}

function FormulaBlock({ block }: { block: ExplanationBlock }) {
  const latex = typeof block.data?.latex === "string" ? block.data.latex : "";
  const explanation = typeof block.data?.explanation === "string" ? block.data.explanation : "";
  return <div className="exp-block exp-formula"><MarkdownContent content={block.content} />{latex && <RichMarkdown content={`$$\n${latex}\n$$\n\n${explanation}`} />}</div>;
}

function CodeWalkthrough({ block }: { block: ExplanationBlock }) {
  // §56：只有 data.code 才是真正的代码；普通中文说明绝不能塞进 <pre><code>。
  const code = block.data?.code as string | undefined;
  const annotations = (block.data?.annotations as Array<{ line: number; label: string; explanation: string }> | undefined) ?? [];
  return (
    <div className="exp-block exp-code">
      <MarkdownContent content={block.content} />
      {code && <pre className="exp-code-block"><code>{code}</code></pre>}
      {annotations.length > 0 && (
        <ul className="exp-annotations">
          {annotations.map((a, i) => (
            <li key={i} className="exp-annotation">
              <span className="exp-annotation-label">L{a.line} · {a.label}</span>
              <span className="exp-annotation-text"><RichMarkdown content={a.explanation} /></span>
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
          {points.map((p, i) => <li key={i}><RichMarkdown content={p} /></li>)}
        </ol>
      ) : (
        <MarkdownContent content={block.content} />
      )}
    </div>
  );
}

function Handoff({ block }: { block: ExplanationBlock }) {
  return (
    <div className="exp-block exp-handoff">
      <MarkdownContent content={block.content} />
    </div>
  );
}

function Contrast({ block }: { block: ExplanationBlock }) {
  const steps = Array.isArray(block.data?.steps) ? (block.data.steps as string[]) : [];
  return (
    <div className="exp-block exp-contrast">
      <MarkdownContent content={block.content} />
      {steps.length > 0 && (
        <ul className="exp-contrast-list">
          {steps.map((s, i) => <li key={i}><RichMarkdown content={s} /></li>)}
        </ul>
      )}
    </div>
  );
}
