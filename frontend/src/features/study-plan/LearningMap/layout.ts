/** 基于 ELK 的分层 DAG 布局（§17-22）。 */

import ELK, { type ElkNode, type LayoutOptions } from "elkjs/lib/elk.bundled.js";
import type { LearningMapEdge, LearningMapNode, LearningMapResponse } from "../../../api/types";

export interface PositionedNode {
  id: string;
  x: number;
  y: number;
}

export interface LayoutGraph {
  nodes: LearningMapNode[];
  edges: LearningMapEdge[];
}

/** Select the backend-provided graph that should participate in each mode. */
export function selectLayoutGraph(
  data: LearningMapResponse,
  mode: "active" | "full",
): LayoutGraph {
  if (mode === "full") return { nodes: data.nodes, edges: data.edges };

  const primaryRoute = data.primary_route?.length ? data.primary_route : data.active_path ?? [];
  const activeIds = data.active_subgraph_nodes?.length
    ? data.active_subgraph_nodes
    : primaryRoute.length
      ? primaryRoute
      : data.nodes.map((node) => node.id);
  const visible = new Set(activeIds);
  const candidateEdges = data.active_subgraph_edges?.length
    ? data.active_subgraph_edges
    : data.edges;
  return {
    nodes: data.nodes.filter((node) => visible.has(node.id)),
    edges: candidateEdges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

const elk = new ELK();

const NODE_W = 220;
const NODE_H = 96;

/**
 * Deterministic fallback that still reflects the real prerequisite DAG.
 * Nodes are assigned to the longest-path layer from a source; no edges are
 * inferred or added. Cyclic/invalid input is handled by placing the remaining
 * nodes in the last reachable layer without fabricating relationships.
 */
export function layoutDagFallback(
  nodes: LearningMapNode[],
  edges: LearningMapEdge[],
): PositionedNode[] {
  const order = new Map(nodes.map((node, index) => [node.id, index]));
  const ids = new Set(nodes.map((node) => node.id));
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const node of nodes) {
    incoming.set(node.id, 0);
    outgoing.set(node.id, []);
  }
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target) continue;
    outgoing.get(edge.source)?.push(edge.target);
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
  }

  const layers = new Map<string, number>();
  const queue = nodes
    .filter((node) => (incoming.get(node.id) ?? 0) === 0)
    .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  queue.forEach((node) => layers.set(node.id, 0));
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const source = queue[cursor];
    if (!source) continue;
    const sourceLayer = layers.get(source.id) ?? 0;
    for (const targetId of outgoing.get(source.id) ?? []) {
      layers.set(targetId, Math.max(layers.get(targetId) ?? 0, sourceLayer + 1));
      const nextIncoming = (incoming.get(targetId) ?? 0) - 1;
      incoming.set(targetId, nextIncoming);
      if (nextIncoming === 0) {
        const next = nodes.find((node) => node.id === targetId);
        if (next) queue.push(next);
      }
    }
  }

  const maxLayer = Math.max(0, ...layers.values());
  nodes.forEach((node, index) => {
    if (!layers.has(node.id)) layers.set(node.id, maxLayer + 1 + index);
  });
  const byLayer = new Map<number, LearningMapNode[]>();
  for (const node of nodes) {
    const layer = layers.get(node.id) ?? 0;
    const group = byLayer.get(layer) ?? [];
    group.push(node);
    byLayer.set(layer, group);
  }

  return nodes.map((node) => {
    const layer = layers.get(node.id) ?? 0;
    const group = byLayer.get(layer) ?? [node];
    const row = group.findIndex((item) => item.id === node.id);
    return {
      id: node.id,
      x: layer * (NODE_W + 120),
      y: row * (NODE_H + 44),
    };
  });
}

/** ELK 配置（§18）：layered + RIGHT 方向 + orthogonal routing，减少边交叉与节点重叠。 */
const ELK_OPTIONS: LayoutOptions = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.spacing.nodeNode": "40",
  "elk.layered.spacing.nodeNodeBetweenLayers": "90",
  "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
};

/**
 * 用 ELK 计算 DAG 布局。
 */
export async function layoutDagElk(
  nodes: LearningMapNode[],
  edges: LearningMapEdge[],
): Promise<PositionedNode[]> {
  const elkNodes: ElkNode[] = nodes.map((n) => ({
    id: n.id,
    width: NODE_W,
    height: NODE_H,
  }));
  const elkEdges = edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    sources: [e.source],
    targets: [e.target],
  }));

  const graph: ElkNode = {
    id: "root",
    layoutOptions: ELK_OPTIONS,
    children: elkNodes,
    edges: elkEdges,
  };

  const laid = await elk.layout(graph);
  const result = new Map<string, PositionedNode>();
  for (const child of laid.children ?? []) {
    result.set(child.id, { id: child.id, x: child.x ?? 0, y: child.y ?? 0 });
  }
  // 返回节点顺序（node 顺序展示），附带 dim 标记供调用方使用
  return nodes
    .map((n) => result.get(n.id))
    .filter((p): p is PositionedNode => Boolean(p));
}

/** 判断节点是否属于当前学习路径模式（active_path 内，或 active_path 的直接前置）。 */
export function isOnActivePath(
  nodeId: string,
  activePath: string[],
  edges: LearningMapEdge[],
): boolean {
  if (activePath.includes(nodeId)) return true;
  // 直接前置支撑节点也算可见（非隐藏），但可弱化
  return edges.some((e) => e.target === nodeId && activePath.includes(e.source));
}
