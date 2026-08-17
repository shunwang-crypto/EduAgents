import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
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

function Flow({ data, selectedKcId, onSelect }: Props) {
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
    return data.edges.map((e) => ({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      animated: data.recommended_path.includes(e.target) || data.recommended_path.includes(e.source),
      style: { stroke: "#94a3b8", strokeWidth: 1.5 },
    }));
  }, [data]);

  if (!data) {
    return <div style={{ padding: 24, color: "#64748b" }}>正在加载学习地图…</div>;
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect((node.data as KCNodeData).node)}
      fitView
      minZoom={0.3}
      maxZoom={1.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls />
    </ReactFlow>
  );
}

export default function LearningMapView(props: Props) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
