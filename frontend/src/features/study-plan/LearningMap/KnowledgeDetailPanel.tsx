import type { LearningMapNode } from "../../../api/types";
import { masteryText, STATUS_STYLES } from "./statusStyles";
import { reasonCodeToHuman } from "./reasonText";

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
  const prereqName = (id: string) => {
    const pn = allNodes.find((n) => n.id === id);
    return pn ? `${nameOf(id)}（${STATUS_STYLES[pn.status].label}）` : nameOf(id);
  };

  return (
    <div style={{ padding: 16, fontSize: 13, color: "#1e293b" }}>
      <h3 style={{ margin: "0 0 4px" }}>{node.name}</h3>
      <div style={{ color: "#64748b", fontSize: 12, marginBottom: 8 }}>{node.description}</div>

      {/* 主信息：掌握度（大）；Confidence 次级（评估可信度） */}
      <Row
        label="掌握度"
        value={
          <span style={{ fontSize: 16, fontWeight: 700 }}>
            {masteryText(node.mastery)}
          </span>
        }
      />
      <Row
        label="评估可信度"
        value={node.confidence === null ? "?" : `${Math.round(node.confidence * 100)}%`}
      />
      <Row
        label="学习状态"
        value={<span style={{ color: st.color, fontWeight: 600 }}>{st.label}</span>}
      />

      <Section title="前置知识">
        {node.prerequisites.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>无</span>
        ) : (
          node.prerequisites.map((p) => {
            const pn = allNodes.find((n) => n.id === p);
            const ok = pn?.status === "mastered";
            return (
              <div key={p} style={{ color: ok ? "#15803d" : "#b45309" }}>
                {ok ? "✓" : "○"} {prereqName(p)}
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
              {ev.timestamp ? <span style={{ color: "#94a3b8" }}> · {ev.timestamp}</span> : null}
            </div>
          ))
        )}
      </Section>

      <Section title="发现误区">
        {node.misconceptions.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>无</span>
        ) : (
          node.misconceptions.map((m) => (
            <div key={m} style={{ color: "#dc2626" }}>⚠ {m}</div>
          ))
        )}
      </Section>

      <Section title="系统推荐动作">
        {node.locked ? (
          <div style={{ color: "#9ca3af" }}>
            需先掌握以下前置知识：
            <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
              {node.prerequisites
                .filter((p) => allNodes.find((n) => n.id === p)?.status !== "mastered")
                .map((p) => (
                  <li key={p}>{prereqName(p)}</li>
                ))}
            </ul>
          </div>
        ) : node.recommended ? (
          <span style={{ color: "#6366f1", fontWeight: 600 }}>建议优先学习</span>
        ) : (
          <span style={{ color: "#15803d" }}>已掌握，可复习</span>
        )}
      </Section>

      {node.reason_codes.length > 0 && (
        <Section title="为什么推荐这个知识点？">
          <ul style={{ margin: 0, paddingLeft: 18, color: "#475569" }}>
            {node.reason_codes.map((rc) => (
              <li key={rc}>{reasonCodeToHuman(rc)}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "3px 0",
        borderBottom: "1px solid #f1f5f9",
      }}
    >
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
