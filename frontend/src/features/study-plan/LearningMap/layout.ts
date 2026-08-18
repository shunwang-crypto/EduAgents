/** 基于 ELK 的分层 DAG 布局（§17-22）。 */

import ELK, { type ElkNode, type LayoutOptions } from "elkjs/lib/elk.bundled.js";
import type { LearningMapEdge, LearningMapNode } from "../../../api/types";

export interface PositionedNode {
  id: string;
  x: number;
  y: number;
}

const elk = new ELK();

const NODE_W = 220;
const NODE_H = 96;

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
