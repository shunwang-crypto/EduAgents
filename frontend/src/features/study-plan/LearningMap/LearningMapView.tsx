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
import { Crosshair } from "lucide-react";
import type { LearningMapNode, LearningMapResponse, PlanStep } from "../../../api/types";
import KnowledgeNode, { type KCNodeData } from "./KnowledgeNode";
import {
  layoutDagElk,
  layoutDagFallback,
  selectLayoutGraph,
  type PositionedNode,
} from "./layout";

const nodeTypes = { kc: KnowledgeNode };

interface Props {
  data: LearningMapResponse | null;
  selectedKcId: string | null;
  planStepStatusByKc?: ReadonlyMap<string, PlanStep["status"]>;
  onSelect: (kc: LearningMapNode) => void;
}

/** 图拓扑签名：节点 id 集 + 边集。mastery/confidence 数值变化不改变签名（§20/§21）。 */
function topologySignature(data: LearningMapResponse | null): string {
  if (!data) return "";
  const nodeIds = data.nodes.map((n) => n.id).sort().join(",");
  const edges = data.edges.map((e) => `${e.source}>${e.target}`).sort().join(",");
  const subNodes = (data.active_subgraph_nodes ?? []).slice().sort().join(",");
  const subEdges = (data.active_subgraph_edges ?? [])
    .map((e) => `${e.source}>${e.target}`)
    .sort()
    .join(",");
  const route = (data.primary_route ?? []).join("->");
  return `${nodeIds}|${edges}|sub:${subNodes}|${subEdges}|rt:${route}`;
}

const LEGEND: { icon: string; label: string }[] = [
  { icon: "✓", label: "已完成" },
  { icon: "●", label: "已掌握" },
  { icon: "◐", label: "学习中" },
  { icon: "△", label: "薄弱" },
  { icon: "?", label: "尚待评估" },
  { icon: "★", label: "当前推荐" },
  { icon: "🔒", label: "前置未满足" },
];

type MapMode = "active" | "full";

function Flow({ data, selectedKcId, planStepStatusByKc, onSelect }: Props) {
  const { fitView } = useReactFlow();
  const prevViewSignature = useRef<string>("");
  const [positions, setPositions] = useState<PositionedNode[]>([]);
  const [mode, setMode] = useState<MapMode>("active");
  const layoutSeq = useRef(0);

  const topology = data ? topologySignature(data) : "";

  // Active mode lays out only the goal prerequisite closure; full mode lays
  // out the complete graph. Both use only edges supplied by the backend.
  const primaryRoute = data?.primary_route?.length ? data.primary_route : (data?.active_path ?? []);
  const activeNodeList = data?.active_subgraph_nodes?.length
    ? data.active_subgraph_nodes
    : primaryRoute.length
    ? primaryRoute
    : (data?.nodes.map((node) => node.id) ?? []);
  const subNodeIds = useMemo(() => new Set(activeNodeList), [activeNodeList]);
  const isActiveMode = mode === "active";
  const layoutGraph = useMemo(
    () => (data ? selectLayoutGraph(data, mode) : { nodes: [], edges: [] }),
    // Status/mastery updates do not alter the topology captured by this key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [topology, mode],
  );

  // §20：ELK 布局 async 安全。只在 topology 变化时重新布局；用 request seq 丢弃旧结果。
  useEffect(() => {
    if (!data) return;
    const seq = ++layoutSeq.current;
    let cancelled = false;
    setPositions([]);
    layoutDagElk(layoutGraph.nodes, layoutGraph.edges)
      .then((pos) => {
        if (cancelled || seq !== layoutSeq.current) return;
        setPositions(pos);
      })
      .catch(() => {
        if (cancelled || seq !== layoutSeq.current) return;
        setPositions(layoutDagFallback(layoutGraph.nodes, layoutGraph.edges));
      });
    return () => {
      cancelled = true;
    };
  }, [topology, mode, layoutGraph]);

  // §38/§84：只高亮真实相邻 route pair（禁止 A→C shortcut 被误高亮）。
  const routePairs = useMemo(() => {
    const pairs = new Set<string>();
    for (let i = 0; i < primaryRoute.length - 1; i++) {
      pairs.add(`${primaryRoute[i]}->${primaryRoute[i + 1]}`);
    }
    return pairs;
  }, [primaryRoute]);

  const posMap = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);

  const nodes: Node<KCNodeData>[] = useMemo(() => {
    if (!data) return [];
    return data.nodes.map((n) => {
      const p = posMap.get(n.id) ?? { x: 0, y: 0 };
      const inActive = isActiveMode ? subNodeIds.has(n.id) : true;
      const onRoute = primaryRoute.includes(n.id);
      return {
        id: n.id,
        type: "kc",
        position: { x: p.x, y: p.y },
        data: { node: n, planStatus: planStepStatusByKc?.get(n.id) },
        selected: selectedKcId === n.id,
        // §37：当前学习路线模式只显示 active_subgraph（含未来 locked 节点与支撑前置）；
        // 完整知识图模式显示全部。
        hidden: isActiveMode && !inActive,
        style: {
          opacity:
            isActiveMode && onRoute && primaryRoute.length > 0
              ? 1
              : isActiveMode
              ? 0.7
              : 1,
        },
      } as Node<KCNodeData>;
    });
  }, [
    data,
    posMap,
    mode,
    subNodeIds,
    primaryRoute,
    isActiveMode,
    selectedKcId,
    planStepStatusByKc,
  ]);

  const edges: Edge[] = useMemo(() => {
    if (!data) return [];
    // Reuse the exact graph selected for layout. This prevents a malformed or
    // stale active_subgraph edge from rendering against a hidden node, and
    // guarantees that every displayed edge is supplied by the backend.
    const base = isActiveMode ? layoutGraph.edges : data.edges;
    return base.map((e) => {
      const onRoute = routePairs.has(`${e.source}->${e.target}`);
      const inSub = subNodeIds.has(e.source) && subNodeIds.has(e.target);
      // §38/§84：主学习线边在两种模式下都高亮，且只高亮真实相邻 pair。
      const onActive = onRoute;
      return {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        // §22/§84：仅真实相邻 route pair 高亮；其余中性
        animated: onActive,
        style: onActive
          ? { stroke: "#176b55", strokeWidth: 2.6 }
          : isActiveMode && inSub
          ? { stroke: "#94a3b8", strokeWidth: 1.5 }
          : { stroke: "#94a3b8", strokeWidth: 1.2, strokeDasharray: "4 3", opacity: 0.5 },
        markerEnd: {
          type: "arrowclosed",
          color: onActive ? "#176b55" : "#94a3b8",
        },
      };
    });
  }, [data, routePairs, subNodeIds, isActiveMode, layoutGraph]);

  // 当前应聚焦的知识点：用户选中 > 系统推荐 > 主线起点
  const focusId = selectedKcId ?? data?.current_recommended_kc ?? primaryRoute[0] ?? null;

  /** 默认视野 = 当前知识点 + 前后 2~3 个相关节点。
   *
   * 主线上取「前 2 + 当前 + 后 3」的窗口；不在主线上时退化为「当前 + 直接前置 + 直接后继」。
   * 绝不把整条长路线一次 fitView，否则节点会被缩成一条看不清的细线；
   * 需要俯视全局时切到「完整知识图」，那里才 fit 全图。
   */
  const focusIds = useMemo((): string[] => {
    if (!data) return [];
    if (!isActiveMode) return data.nodes.map((node) => node.id);
    if (!focusId) return activeNodeList.slice(0, 5);
    const routeIndex = primaryRoute.indexOf(focusId);
    if (routeIndex >= 0) {
      const window = primaryRoute.slice(Math.max(0, routeIndex - 2), routeIndex + 4);
      // A primary route is intentionally only one valid path. Include all
      // direct prerequisites of the focused node so converging DAG branches
      // remain readable in the default viewport as well.
      const directPrereqs = layoutGraph.edges
        .filter((edge) => edge.target === focusId)
        .map((edge) => edge.source);
      return [...new Set([...window, ...directPrereqs])];
    }
    // 不在主线上（例如用户点了旁支节点）：聚焦它与直接相邻的前置 / 后继
    const node = data.nodes.find((n) => n.id === focusId);
    const prereqs = (node?.prerequisites ?? []).slice(0, 2);
    const dependents = data.edges
      .filter((e) => e.source === focusId)
      .map((e) => e.target)
      .slice(0, 3);
    return [focusId, ...prereqs, ...dependents];
  }, [data, isActiveMode, focusId, primaryRoute, activeNodeList]);

  const focusOnIds = useCallback(
    (ids: string[]) => {
      const targets = nodes.filter((node) => ids.includes(node.id) && !node.hidden);
      if (!targets.length) return;
      requestAnimationFrame(() =>
        fitView({
          nodes: targets,
          padding: isActiveMode ? 0.26 : 0.16,
          duration: 320,
          // 只聚焦少量节点时不要过度放大，保持可读且稳定的比例
          maxZoom: isActiveMode ? 1.1 : 1,
        })
      );
    },
    [nodes, fitView, isActiveMode]
  );

  // 只在图拓扑 / 模式 / 推荐点变化时重新取景：
  // 用户手动点节点或平移之后，视口不再被抢走。
  useEffect(() => {
    if (!data || positions.length === 0) return;
    const viewSignature = `${topology}|mode:${mode}|rec:${data.current_recommended_kc ?? ""}`;
    if (!topology || viewSignature === prevViewSignature.current) return;
    prevViewSignature.current = viewSignature;
    focusOnIds(focusIds);
  }, [topology, mode, positions.length, data, focusIds, focusOnIds]);

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
          当前学习路线
        </button>
        <button
          type="button"
          className={`learning-map-mode-btn ${mode === "full" ? "active" : ""}`}
          onClick={() => setMode("full")}
        >
          完整知识图
        </button>
        {/* 平移 / 缩放之后可一键回到当前知识点附近 */}
        <button
          type="button"
          className="learning-map-mode-btn learning-map-recenter"
          onClick={() => focusOnIds(focusIds)}
          disabled={focusIds.length === 0}
          title="回到当前知识点"
        >
          <Crosshair size={13} aria-hidden /> 回到当前
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
