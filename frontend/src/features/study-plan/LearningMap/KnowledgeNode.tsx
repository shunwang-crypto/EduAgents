import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { LearningMapNode } from "../../../api/types";
import { masteryText, STATUS_STYLES } from "./statusStyles";

export type KCNodeData = {
  node: LearningMapNode;
};

export default function KnowledgeNode({ data }: NodeProps) {
  const node = (data as KCNodeData).node;
  const st = STATUS_STYLES[node.status];
  const ring = node.recommended
    ? "0 0 0 3px #6366f1"
    : node.locked
      ? "0 0 0 2px #e5e7eb"
      : "none";

  return (
    <div
      style={{
        minWidth: 150,
        padding: "10px 12px",
        borderRadius: 10,
        border: `2px solid ${st.border}`,
        background: st.bg,
        boxShadow: ring,
        opacity: node.locked ? 0.65 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ fontSize: 13 }}>{node.name}</strong>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: "#fff",
            background: st.color,
            borderRadius: 999,
            width: 20,
            height: 20,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {st.badge}
        </span>
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: "#334155" }}>
        掌握度：<b>{masteryText(node.mastery)}</b>
      </div>
      <div style={{ marginTop: 2, fontSize: 11, color: st.color }}>{st.label}</div>
      <div style={{ marginTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {node.recommended && (
          <span style={chip("#6366f1")}>★ 推荐</span>
        )}
        {node.locked && <span style={chip("#9ca3af")}>🔒 未解锁</span>}
        {node.misconceptions.length > 0 && (
          <span style={chip("#dc2626")}>⚠ 误区</span>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function chip(color: string): React.CSSProperties {
  return {
    fontSize: 10,
    color: "#fff",
    background: color,
    borderRadius: 6,
    padding: "1px 6px",
  };
}
