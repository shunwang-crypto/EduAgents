import type { LearningMapNode } from "../../../api/types";
import { masteryText, STATUS_STYLES } from "./statusStyles";

interface Props {
  node: LearningMapNode | null;
  allNodes: LearningMapNode[];
}

export default function KnowledgeDetailPanel({ node, allNodes }: Props) {
  if (!node) {
    return (
      <div style={{ padding: 16, color: "#94a3b8", fontSize: 13 }}>
        点击左侧节点查看详情。
      </div>
    );
  }
  const st = STATUS_STYLES[node.status];
  const nameOf = (id: string) => allNodes.find((n) => n.id === id)?.name ?? id;

  return (
    <div style={{ padding: 16, fontSize: 13, color: "#1e293b" }}>
      <h3 style={{ margin: "0 0 8px" }}>{node.name}</h3>
      <p style={{ color: "#64748b", marginTop: 0 }}>{node.description}</p>

      <Row label="掌握度" value={masteryText(node.mastery)} />
      <Row label="置信度" value={node.confidence === null ? "?" : `${Math.round(node.confidence * 100)}%`} />
      <Row label="状态" value={<span style={{ color: st.color, fontWeight: 600 }}>{st.label}</span>} />

      <Section title="前置依赖">
        {node.prerequisites.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>无</span>
        ) : (
          node.prerequisites.map((p) => {
            const pn = allNodes.find((n) => n.id === p);
            const ok = pn?.status === "mastered";
            return (
              <div key={p}>
                {ok ? "✓" : "○"} {nameOf(p)}
                <span style={{ color: ok ? "#15803d" : "#b45309" }}>
                  {" "}({pn ? STATUS_STYLES[pn.status].label : "?"})
                </span>
              </div>
            );
          })
        )}
      </Section>

      <Section title="最近证据">
        {node.recent_evidence.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>暂无</span>
        ) : (
          node.recent_evidence.slice(0, 5).map((ev, i) => (
            <div key={i}>
              {ev.correctness === "correct" ? "✓" : ev.correctness === "incorrect" ? "×" : "○"}{" "}
              {ev.type}
            </div>
          ))
        )}
      </Section>

      <Section title="误区">
        {node.misconceptions.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>无</span>
        ) : (
          node.misconceptions.map((m) => (
            <div key={m} style={{ color: "#dc2626" }}>⚠ {m}</div>
          ))
        )}
      </Section>

      <Section title="推荐动作">
        {node.recommended ? (
          <span style={{ color: "#6366f1", fontWeight: 600 }}>建议优先学习</span>
        ) : node.locked ? (
          <span style={{ color: "#9ca3af" }}>等待前置解锁</span>
        ) : (
          <span style={{ color: "#15803d" }}>已掌握，可复习</span>
        )}
      </Section>

      {node.reason_codes.length > 0 && (
        <Section title="推荐原因">
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {node.reason_codes.map((rc) => (
              <span
                key={rc}
                style={{
                  fontSize: 10,
                  background: "#eef2ff",
                  color: "#4338ca",
                  borderRadius: 6,
                  padding: "1px 6px",
                }}
              >
                {rc}
              </span>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid #f1f5f9" }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  );
}
