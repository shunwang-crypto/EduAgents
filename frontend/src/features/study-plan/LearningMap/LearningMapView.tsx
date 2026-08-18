import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { layoutDagElk, isOnActivePath, type PositionedNode } from "./layout";

const nodeTypes = { kc: KnowledgeNode };

interface Props {
  data: LearningMapResponse | null;
  selectedKcId: string | null;
  onSelect: (kc: LearningMapNode) => void;
}

/** 图拓扑签名：节点 id 集 + 边集。mastery/confidence 数值变化不改变签名（§20/§21）。 */
function topologySignature(data: LearningMapResponse | null): string {
  if (!data) return "";
  const nodeIds = data.nodes.map((n) => n.id).sort().join(",");
  const edges = data.edges.map((e) => `${e.source}>${e.target}`).sort().join(",");
  return `${nodeIds}|${edges}`;
}

const LEGEND: { icon: string; label: string }[] = [
  { icon: "✓", label: "已掌握" },
  { icon: "◐", label: "学习中" },
  { icon: "△", label: "薄弱" },
  { icon: "?", label: "未评估" },
  { icon: "★", label: "当前推荐" },
  { icon: "🔒", label: "前置未满足" },
];

type MapMode = "active" | "full";

function Flow({ data, selectedKcId, onSelect }: Props) {
  const { fitView } = useReactFlow();
  const prevTopology = useRef<string>("");
  const [positions, setPositions] = useState<PositionedNode[]>([]);
  const [mode, setMode] = useState<MapMode>("active");
  const layoutSeq = useRef(0);

  const topology = data ? topologySignature(data) : "";

  // §20：ELK 布局 async 安全。只在 topology 变化时重新布局；用 request seq 丢弃旧结果。
  useEffect(() => {
    if (!data) return;
    const seq = ++layoutSeq.current;
    let cancelled = false;
    layoutDagElk(data.nodes, data.edges)
      .then((pos) => {
        if (cancelled || seq !== layoutSeq.current) return;
        setPositions(pos);
      })
      .catch(() => {
        if (cancelled || seq !== layoutSeq.current) return;
        // ELK 失败兜底：按层级简单排布
        setPositions(
          data.nodes.map((n, i) => ({ id: n.id, x: (i % 3) * 240, y: Math.floor(i / 3) * 140 }))
        );
      });
    return () => {
      cancelled = true;
    };
  }, [topology]); // 仅 topology；mastery/confidence 变化不重新 layout

  const activePath = data?.active_path ?? [];

  const posMap = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);

  const nodes: Node<KCNodeData>[] = useMemo(() => {
    if (!data) return [];
    return data.nodes.map((n) => {
      const p = posMap.get(n.id) ?? { x: 0, y: 0 };
      const inActivePath =
        mode === "active" ? isOnActivePath(n.id, activePath, data.edges) : true;
      return {
        id: n.id,
        type: "kc",
        position: { x: p.x, y: p.y },
        data: { node: n },
        selected: selectedKcId === n.id,
        // §30：当前学习路径模式隐藏非相关节点（半透明），完整图模式全部显示
        hidden: mode === "active" && !inActivePath,
        style: {
          opacity:
            mode === "active" && !activePath.includes(n.id) && activePath.length > 0
              ? 0.55
              : 1,
        },
      } as Node<KCNodeData>;
    });
  }, [data, posMap, mode, activePath, selectedKcId]);

  const edges: Edge[] = useMemo(() => {
    if (!data) return [];
    return data.edges.map((e) => {
      const onActive = activePath.includes(e.source) && activePath.includes(e.target);
      return {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        // §22：active path 边高亮；普通 prerequisite 中性
        animated: onActive,
        style: onActive
          ? { stroke: "#6366f1", strokeWidth: 2.6 }
          : { stroke: "#94a3b8", strokeWidth: 1.5 },
        markerEnd: { type: "arrowclosed", color: onActive ? "#6366f1" : "#94a3b8" },
      };
    });
  }, [data, activePath]);

  // §21：首次 topology 布局完成后 fitView（padding 0.15~0.20）；mastery 更新不 fitView。
  useEffect(() => {
    if (!data) return;
    if (topology && topology !== prevTopology.current && positions.length > 0) {
      prevTopology.current = topology;
      requestAnimationFrame(() => fitView({ padding: 0.18, duration: 300 }));
    }
  }, [topology, positions.length, fitView, data]);

  const handleNodeClick = useCallback(
    (_: unknown, node: Node<KCNodeData>) => onSelect((node.data as KCNodeData).node),
    [onSelect]
  );

  if (!data) {
    return <div style={{ padding: 24, color: "#64748b" }}>正在加载学习地图…</div>;
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* §30：地图模式切换 */}
      <div className="learning-map-mode-switch">
        <button
          type="button"
          className={`learning-map-mode-btn ${mode === "active" ? "active" : ""}`}
          onClick={() => setMode("active")}
        >
          当前学习路径
        </button>
        <button
          type="button"
          className={`learning-map-mode-btn ${mode === "full" ? "active" : ""}`}
          onClick={() => setMode("full")}
        >
          完整知识图
        </button>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView={false}
        minZoom={0.3}
        maxZoom={1.6}
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
