import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { LearningMapNode, LearningMapResponse } from "../../../api/types";
import KnowledgeNode, { type KCNodeData } from "./KnowledgeNode";
import { layoutDag } from "./layout";

const nodeTypes = { kc: KnowledgeNode };

interface Props {
  data: LearningMapResponse | null;
  selectedKcId: string | null;
  onSelect: (kc: LearningMapNode) => void;
}

/**
 * 图拓扑签名：节点 id 集 + 边集。mastery/confidence 数值变化不会改变签名。
 * §29：只有拓扑变化才 fitView，数值变化保持用户 viewport，避免画布跳动。
 */
function topologySignature(data: LearningMapResponse | null): string {
  if (!data) return "";
  const nodeIds = data.nodes.map((n) => n.id).sort().join(",");
  const edges = data.edges
    .map((e) => `${e.source}>${e.target}`)
    .sort()
    .join(",");
  return `${nodeIds}|${edges}`;
}

const LEGEND: { icon: string; label: string }[] = [
  { icon: "✓", label: "已掌握" },
  { icon: "◐", label: "学习中" },
  { icon: "△", label: "薄弱" },
  { icon: "?", label: "未评估" },
  { icon: "★", label: "推荐" },
  { icon: "🔒", label: "前置未满足" },
];

function Flow({ data, selectedKcId, onSelect }: Props) {
  const { fitView } = useReactFlow();
  const prevTopology = useRef<string>("");

  const nodes: Node<KCNodeData>[] = useMemo(() => {
    if (!data) return [];
    const pos = layoutDag(data.nodes, data.edges);
    const posMap = new Map(pos.map((p) => [p.id, p]));
    return data.nodes.map((n) => {
      const p = posMap.get(n.id) ?? { x: 0, y: 0 };
      return {
        id: n.id,
        type: "kc",
        position: { x: p.x, y: p.y },
        data: { node: n },
        selected: selectedKcId === n.id,
      } as Node<KCNodeData>;
    });
  }, [data, selectedKcId]);

  const edges: Edge[] = useMemo(() => {
    if (!data) return [];
    return data.edges.map((e) => {
      const onRecommendedPath =
        data.recommended_path.includes(e.source) && data.recommended_path.includes(e.target);
      return {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        // §28：推荐路径边加粗高亮；普通 prerequisite 边保持常规。
        animated: onRecommendedPath,
        style: onRecommendedPath
          ? { stroke: "#6366f1", strokeWidth: 2.5 }
          : { stroke: "#94a3b8", strokeWidth: 1.5 },
        markerEnd: { type: "arrowclosed", color: onRecommendedPath ? "#6366f1" : "#94a3b8" },
      };
    });
  }, [data]);

  // §29：仅拓扑变化时 fitView（首次加载 / 生成后图结构变化）。
  useEffect(() => {
    const sig = topologySignature(data);
    if (sig && sig !== prevTopology.current) {
      prevTopology.current = sig;
      // 延后一拍，等节点/边真正渲染后再 fitView
      requestAnimationFrame(() => fitView({ padding: 0.15, duration: 300 }));
    }
  }, [data, fitView]);

  const handleNodeClick = useCallback(
    (_: unknown, node: Node<KCNodeData>) => onSelect((node.data as KCNodeData).node),
    [onSelect]
  );

  if (!data) {
    return <div style={{ padding: 24, color: "#64748b" }}>正在加载学习地图…</div>;
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView={false}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
      </ReactFlow>
      <div className="learning-map-legend">
        {LEGEND.map((l) => (
          <span key={l.label} className="learning-map-legend-item">
            <span className="learning-map-legend-icon">{l.icon}</span>
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function LearningMapView(props: Props) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
