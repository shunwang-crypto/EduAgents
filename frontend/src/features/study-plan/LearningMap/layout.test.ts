import { describe, expect, it } from "vitest";
import type { LearningMapEdge, LearningMapNode, LearningMapResponse } from "../../../api/types";
import { layoutDagFallback, selectLayoutGraph } from "./layout";

function node(id: string): LearningMapNode {
  return {
    id,
    name: id,
    description: "",
    difficulty: "medium",
    mastery: null,
    confidence: null,
    status: "unknown",
    recommended: false,
    locked: false,
    prerequisites: [],
    misconceptions: [],
    recent_evidence: [],
    reason_codes: [],
  };
}

function edge(source: string, target: string): LearningMapEdge {
  return { source, target, relation: "prerequisite", weight: 1 };
}

describe("learning map DAG layout", () => {
  it("keeps converging prerequisites parallel and puts branches in the next layer", () => {
    const nodes = ["python", "numpy", "linear", "tensor", "autograd", "cnn", "rnn"].map(node);
    const edges = [
      edge("python", "tensor"),
      edge("numpy", "tensor"),
      edge("linear", "tensor"),
      edge("tensor", "autograd"),
      edge("autograd", "cnn"),
      edge("autograd", "rnn"),
    ];

    const positions = new Map(layoutDagFallback(nodes, edges).map((item) => [item.id, item]));
    expect(positions.get("python")?.x).toBe(positions.get("numpy")?.x);
    expect(positions.get("numpy")?.x).toBe(positions.get("linear")?.x);
    expect(positions.get("tensor")!.x).toBeGreaterThan(positions.get("python")!.x);
    expect(positions.get("autograd")!.x).toBeGreaterThan(positions.get("tensor")!.x);
    expect(positions.get("cnn")?.x).toBe(positions.get("rnn")?.x);
    expect(positions.get("cnn")!.x).toBeGreaterThan(positions.get("autograd")!.x);
    expect(positions.get("python")?.y).not.toBe(positions.get("numpy")?.y);
    expect(positions.get("cnn")?.y).not.toBe(positions.get("rnn")?.y);
  });

  it("lays out only the backend active subgraph in active mode", () => {
    const data = {
      nodes: ["a", "b", "c", "outside"].map(node),
      edges: [edge("a", "b"), edge("b", "c"), edge("outside", "c")],
      active_subgraph_nodes: ["a", "b", "c"],
      active_subgraph_edges: [edge("a", "b"), edge("b", "c")],
      primary_route: ["a", "b", "c"],
      active_path: ["a", "b", "c"],
    } as unknown as LearningMapResponse;

    expect(selectLayoutGraph(data, "active").nodes.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(selectLayoutGraph(data, "active").edges).toEqual([
      edge("a", "b"),
      edge("b", "c"),
    ]);
    expect(selectLayoutGraph(data, "full").nodes).toHaveLength(4);
    expect(selectLayoutGraph(data, "full").edges).toHaveLength(3);
  });

  it("filters malformed active edges instead of inventing replacement edges", () => {
    const data = {
      nodes: ["a", "b", "outside"].map(node),
      edges: [edge("a", "b")],
      active_subgraph_nodes: ["a", "b"],
      active_subgraph_edges: [edge("outside", "b")],
      primary_route: [],
      active_path: [],
    } as unknown as LearningMapResponse;

    expect(selectLayoutGraph(data, "active").edges).toEqual([]);
  });
});
