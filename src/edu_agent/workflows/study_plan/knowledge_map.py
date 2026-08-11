import re
from typing import Iterable, List

from edu_agent.workflows.study_plan.schemas import (
    DecompositionResult,
    KnowledgeMap,
    KnowledgeNode,
    LearningStageSuggestion,
    STAGE_COUNT,
    StudentInput,
)


def _clean_title(value: str) -> str:
    value = re.sub(r"^[\d一二三四五六七八九十]+[.、：:]\s*", "", value.strip())
    value = re.sub(r"^(先|再|随后|最后)", "", value).strip()
    value = re.sub(r"^(系统)?(学习|理解|掌握|了解|熟悉)\s*", "", value).strip()
    for separator in ("：", ":"):
        if separator in value:
            prefix = value.split(separator, 1)[0].strip()
            if 2 <= len(prefix) <= 24:
                value = prefix
                break
    if len(value) > 24:
        value = re.split(r"[，；。]|并(?:完成|实现|使用|验证|说明)|以及|从而|以便", value, maxsplit=1)[0].strip()
    if len(value) > 24 and "、" in value:
        value = value.split("、", 1)[0].strip()
    if len(value) > 24:
        value = f"{value[:21].rstrip()}..."
    return value or "未命名知识点"


def _unique_items(items: Iterable[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        raw = item.strip()
        title = _clean_title(raw)
        key = re.sub(r"\s+", "", title).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((title, raw))
    return result


def _normalize_stages(stages: list[LearningStageSuggestion]) -> list[LearningStageSuggestion]:
    """兜底：确保恰好 3 个阶段（缺的补默认，多的截断）。"""
    defaults = [
        ("stage-1", "基础准备", "补齐必要背景、前置知识与环境"),
        ("stage-2", "核心学习", "掌握核心概念、方法与原理"),
        ("stage-3", "综合应用", "通过案例、小项目整合知识并总结"),
    ]
    ordered = sorted((stages or [])[:STAGE_COUNT], key=lambda s: s.order)
    result: list[LearningStageSuggestion] = []
    for order in range(1, STAGE_COUNT + 1):
        stage = next((s for s in ordered if s.order == order), None)
        if stage is None or not stage.title.strip():
            stage_id, title, objective = defaults[order - 1]
            stage = LearningStageSuggestion(stage_id=stage_id, title=title, objective=objective, order=order)
        result.append(stage)
    return result


def build_knowledge_map(
    student_input: StudentInput,
    decomposition: DecompositionResult,
) -> KnowledgeMap:
    """Build a stable, UI-friendly knowledge map without another LLM call.

    - 一级结构固定 3 个阶段（stage_id/stage_title/stage_order）。
    - **按阶段分桶生成**：stage1_nodes + stage2_nodes + stage3_nodes 顺序拼接，
      node.id（=kc_id）严格按 1..N 连续编号，与 stage 顺序一致；
      每个阶段即使输入为空也有兜底节点（Stage2 缺 core 同样补）。
    - 阶段映射：prerequisite→Stage1 / core→Stage2 / application→Stage3。
    - 不允许出现练习/题目语义；活动类型限定为学习活动（阅读/案例/项目等）。
    """

    node_index = 1
    stages = _normalize_stages(decomposition.stages)

    prerequisite_items = _unique_items(decomposition.prerequisite_concepts)
    core_items = _unique_items(decomposition.core_concepts)
    application_items = _unique_items(decomposition.application_directions)
    prerequisite_titles = [title for title, _ in prerequisite_items]
    core_titles = [title for title, _ in core_items]

    def make(
        title: str,
        summary: str,
        category: str,
        difficulty: str,
        minutes: int,
        stage: LearningStageSuggestion,
        prerequisites: list[str],
        objective: str,
    ) -> KnowledgeNode:
        nonlocal node_index
        node = KnowledgeNode(
            id=f"knowledge-{node_index}",
            title=title,
            category=category,
            summary=summary,
            prerequisites=prerequisites,
            difficulty=difficulty,
            estimated_minutes=minutes,
            stage_id=stage.stage_id,
            stage_title=stage.title,
            stage_order=stage.order,
            learning_objective=objective,
        )
        node_index += 1
        return node

    topic = student_input.topic

    # ---- Stage 1：前置知识（无则补学习准备节点） ----
    stage1_nodes: List[KnowledgeNode] = []
    for title, summary in prerequisite_items:
        stage1_nodes.append(make(
            title=title, summary=summary, category="前置知识", difficulty="入门", minutes=30,
            stage=stages[0], prerequisites=[],
            objective=f"能用自己的话说明「{title}」并完成一个最小示例。"
        ))
    if not stage1_nodes:
        stage1_nodes.append(make(
            title=f"{topic} 核心术语与整体认识",
            summary=f"了解「{topic}」的核心术语、学习环境与整体知识结构。",
            category="前置知识", difficulty="入门", minutes=30,
            stage=stages[0], prerequisites=[],
            objective=f"能用自己的话说明「{topic}」的基本概念与用途。"
        ))

    # ---- Stage 2：核心知识（无则补主线方法节点，这是关键兜底） ----
    stage2_nodes: List[KnowledgeNode] = []
    for title, summary in core_items:
        stage2_nodes.append(make(
            title=title, summary=summary, category="核心知识", difficulty="中等", minutes=45,
            stage=stages[1], prerequisites=prerequisite_titles[:3],
            objective=f"能解释「{title}」的核心原理，并在学习目标场景中正确使用。"
        ))
    if not stage2_nodes:
        stage2_nodes.append(make(
            title=f"{topic} 核心概念与主线方法",
            summary=f"掌握「{topic}」的核心概念、关键方法与主流程。",
            category="核心知识", difficulty="中等", minutes=45,
            stage=stages[1], prerequisites=prerequisite_titles[:3],
            objective=f"能解释「{topic}」的核心概念，并在学习目标场景中应用主线方法。"
        ))

    # ---- Stage 3：综合应用（无则补综合案例与总结节点） ----
    stage3_nodes: List[KnowledgeNode] = []
    for title, summary in application_items:
        stage3_nodes.append(make(
            title=title, summary=summary, category="实践应用", difficulty="实践", minutes=60,
            stage=stages[2], prerequisites=core_titles[:4],
            objective=f"独立完成「{title}」并留下可检查的学习产出。"
        ))
    if not stage3_nodes:
        stage3_nodes.append(make(
            title=f"{topic} 综合案例与知识总结",
            summary=f"通过案例或小项目整合「{topic}」所学知识并输出总结。",
            category="实践应用", difficulty="实践", minutes=60,
            stage=stages[2], prerequisites=core_titles[:4],
            objective=f"独立完成「{topic}」的综合案例或小项目并输出复盘总结。"
        ))

    nodes = stage1_nodes + stage2_nodes + stage3_nodes
    return KnowledgeMap(
        topic=topic,
        nodes=nodes,
        recommended_path=[n.id for n in nodes],
    )
