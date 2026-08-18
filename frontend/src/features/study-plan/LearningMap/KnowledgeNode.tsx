import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { LearningMapNode } from "../../../api/types";
import { STATUS_STYLES } from "./statusStyles";
import { masteryText } from "../presentation/learningMapText";
import { STATUS_GLYPH } from "../presentation/statusText";

export type KCNodeData = {
  node: LearningMapNode;
};

export default function KnowledgeNode({ data }: NodeProps) {
  const node = (data as KCNodeData).node;
  const st = STATUS_STYLES[node.status];
  const glyph = STATUS_GLYPH[node.status];
  const ring = node.recommended
    ? "0 0 0 3px #6366f1"
    : node.locked
      ? "0 0 0 2px #e5e7eb"
      : "none";

  return (
    <div
      style={{
        width: 220,
        minHeight: 92,
        padding: "10px 12px",
        borderRadius: 10,
        border: `2px solid ${st.border}`,
        background: st.bg,
        boxShadow: ring,
        opacity: node.locked ? 0.72 : 1,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Handle type="target" position={Position.Left} />

      {/* §19：标题最多两行，完整标题用 title/tooltip */}
      <strong
        style={{
          fontSize: 13,
          lineHeight: 1.3,
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
        title={node.name}
      >
        {node.name}
      </strong>

      {/* 掌握度：UNKNOWN 显示 ? · 未评估 */}
      <div style={{ marginTop: 6, fontSize: 12, color: "#334155" }}>
        掌握度：<b>{masteryText(node.mastery)}</b>
        {node.mastery === null || node.mastery === undefined ? " · 未评估" : ""}
      </div>

      {/* 状态文字 + 图标（不只靠颜色） */}
      <div style={{ marginTop: 2, fontSize: 11, color: st.color, fontWeight: 600 }}>
        {glyph} {st.label}
      </div>

      <div style={{ marginTop: "auto", paddingTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {node.recommended && <span style={chip("#6366f1")}>★ 当前推荐</span>}
        {node.locked && <span style={chip("#9ca3af")}>🔒 前置未满足</span>}
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
