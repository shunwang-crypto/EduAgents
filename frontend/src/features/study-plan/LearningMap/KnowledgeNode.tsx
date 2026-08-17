import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { LearningMapNode } from "../../../api/types";
import { masteryText, STATUS_STYLES } from "./statusStyles";

export type KCNodeData = {
  node: LearningMapNode;
};

function statusIcon(node: LearningMapNode): { glyph: string; title: string } {
  if (node.locked) return { glyph: "🔒", title: "前置未满足" };
  if (node.status === "mastered") return { glyph: "✓", title: "已掌握" };
  if (node.status === "learning") return { glyph: "◐", title: "学习中" };
  if (node.status === "weak") return { glyph: "△", title: "薄弱" };
  return { glyph: "?", title: "未评估" };
}

export default function KnowledgeNode({ data }: NodeProps) {
  const node = (data as KCNodeData).node;
  const st = STATUS_STYLES[node.status];
  const ring = node.recommended
    ? "0 0 0 3px #6366f1"
    : node.locked
      ? "0 0 0 2px #e5e7eb"
      : "none";
  const icon = statusIcon(node);

  return (
    <div
      style={{
        minWidth: 160,
        padding: "10px 12px",
        borderRadius: 10,
        border: `2px solid ${st.border}`,
        background: st.bg,
        boxShadow: ring,
        opacity: node.locked ? 0.7 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
        <strong style={{ fontSize: 13, lineHeight: 1.3 }}>{node.name}</strong>
        <span
          title={icon.title}
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: "#fff",
            background: st.color,
            borderRadius: 999,
            minWidth: 20,
            height: 20,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {icon.glyph}
        </span>
      </div>

      {/* 掌握度：UNKNOWN 必须显示 ?，绝不为 0% */}
      <div style={{ marginTop: 6, fontSize: 12, color: "#334155" }}>
        {node.mastery === null || node.mastery === undefined ? (
          <>掌握度：<b>?</b> · 未评估</>
        ) : (
          <>掌握度：<b>{masteryText(node.mastery)}</b></>
        )}
      </div>

      {/* 状态文字（不只靠颜色）：薄弱/学习中/已掌握/推荐/锁定 */}
      <div style={{ marginTop: 2, fontSize: 11, color: st.color, fontWeight: 600 }}>
        {st.label}
      </div>

      <div style={{ marginTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {node.recommended && <span style={chip("#6366f1")}>★ 推荐</span>}
        {node.locked && <span style={chip("#9ca3af")}>🔒 前置未满足</span>}
        {node.misconceptions.length > 0 && <span style={chip("#dc2626")}>⚠ 误区</span>}
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
