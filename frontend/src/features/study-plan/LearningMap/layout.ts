/** 基于 prerequisite 边的分层 DAG 布局（确定性、无外部依赖）。 */

import type { LearningMapEdge, LearningMapNode } from "../../../api/types";

export interface PositionedNode {
  id: string;
  x: number;
  y: number;
}

const X_GAP = 220;
const Y_GAP = 140;

/** 计算每个节点的层级（最长前置链深度），用于横向分层。 */
function computeLayers(
  nodes: LearningMapNode[],
): Map<string, number> {
  const prereqs = new Map<string, string[]>();
  for (const n of nodes) prereqs.set(n.id, n.prerequisites ?? []);
  const layer = new Map<string, number>();

  const resolve = (id: string, stack: Set<string>): number => {
    if (layer.has(id)) return layer.get(id)!;
    if (stack.has(id)) return 0; // 环保护
    stack.add(id);
    const ps = prereqs.get(id) ?? [];
    let depth = 0;
    for (const p of ps) {
      depth = Math.max(depth, resolve(p, stack) + 1);
    }
    stack.delete(id);
    layer.set(id, depth);
    return depth;
  };

  for (const n of nodes) resolve(n.id, new Set());
  return layer;
}

export function layoutDag(
  nodes: LearningMapNode[],
  _edges: LearningMapEdge[],
): PositionedNode[] {
  const layers = computeLayers(nodes);
  // 每层按出现顺序分配行号
  const perLayerCount = new Map<number, number>();
  return nodes.map((n) => {
    const l = layers.get(n.id) ?? 0;
    const row = perLayerCount.get(l) ?? 0;
    perLayerCount.set(l, row + 1);
    return { id: n.id, x: l * X_GAP, y: row * Y_GAP };
  });
}
