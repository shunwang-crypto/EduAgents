import re
from typing import Iterable

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
    - node.id 即 kc_id（课程内稳定）。
    - 不允许出现练习/题目语义；活动类型限定为学习活动（阅读/案例/项目等）。
    """

    nodes: list[KnowledgeNode] = []
    path: list[str] = []
    node_index = 1
    stages = _normalize_stages(decomposition.stages)

    prerequisite_items = _unique_items(decomposition.prerequisite_concepts)
    core_items = _unique_items(decomposition.core_concepts)
    application_items = _unique_items(decomposition.application_directions)
    prerequisite_titles = [title for title, _ in prerequisite_items]
    core_titles = [title for title, _ in core_items]

    def add_node(
        title: str,
        summary: str,
        category: str,
        difficulty: str,
        minutes: int,
        stage: LearningStageSuggestion,
        prerequisites: list[str],
        objective: str,
        activity: str,
        check: str,
    ) -> None:
        nonlocal node_index
        node_id = f"knowledge-{node_index}"
        node_index += 1
        nodes.append(
            KnowledgeNode(
                id=node_id,
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
                learning_activity=activity,
                check_method=check,
            )
        )
        path.append(node_id)

    for title, summary in prerequisite_items:
        add_node(
            title=title,
            summary=summary,
            category="前置知识",
            difficulty="入门",
            minutes=30,
            stage=stages[0],
            prerequisites=[],
            objective=f"能用自己的话说明「{title}」并完成一个最小示例。",
            activity=f"阅读「{title}」入门资料，运行一个最小示例并整理 3 条笔记。",
            check="不看资料解释「{title}」，并提交示例运行结果。",
        )

    for title, summary in core_items:
        add_node(
            title=title,
            summary=summary,
            category="核心知识",
            difficulty="中等",
            minutes=45,
            stage=stages[1],  # 固定 Stage 2（core 不进 Stage 3）
            prerequisites=prerequisite_titles[:3],
            objective=f"能解释「{title}」的核心原理，并在学习目标场景中正确使用。",
            activity=f"跟随示例代码完成一个直接应用「{title}」的小案例，并记录关键步骤。",
            check="提交案例结果，并说明「{title}」在其中解决了什么问题。",
        )

    for title, summary in application_items:
        add_node(
            title=title,
            summary=summary,
            category="实践应用",
            difficulty="实践",
            minutes=60,
            stage=stages[2],  # 固定 Stage 3
            prerequisites=core_titles[:4],
            objective=f"独立完成「{title}」并留下可检查的学习产出。",
            activity=summary,
            check="提交作品、关键步骤说明和一条复盘记录。",
        )

    # 兜底：保证每个阶段至少一个节点（Stage1 无前置 / Stage3 无应用）
    if not any(n.stage_order == 1 for n in nodes):
        add_node(
            title=f"{student_input.topic} 核心术语与整体认识",
            summary=f"了解「{student_input.topic}」的核心术语、学习环境与整体知识结构。",
            category="前置知识",
            difficulty="入门",
            minutes=30,
            stage=stages[0],
            prerequisites=[],
            objective=f"能用自己的话说明「{student_input.topic}」的基本概念与用途。",
            activity=f"阅读「{student_input.topic}」概述资料，整理核心术语表并熟悉学习环境。",
            check="不看资料解释核心术语，并确认学习环境可用。",
        )
    if not any(n.stage_order == 3 for n in nodes):
        add_node(
            title=f"{student_input.topic} 综合案例与知识总结",
            summary=f"通过案例或小项目整合「{student_input.topic}」所学知识并输出总结。",
            category="实践应用",
            difficulty="实践",
            minutes=60,
            stage=stages[2],
            prerequisites=core_titles[:4],
            objective=f"独立完成「{student_input.topic}」的综合案例或小项目并输出复盘总结。",
            activity=f"完成一个与「{student_input.topic}」相关的综合案例或小项目，整理总结文档。",
            check="提交案例/项目结果、关键步骤说明和复盘记录。",
        )

    if not nodes:
        add_node(
            title=student_input.topic,
            summary=f"围绕「{student_input.topic}」建立概念、方法和应用之间的联系。",
            category="核心知识",
            difficulty="入门",
            minutes=45,
            stage=stages[1],
            prerequisites=[],
            objective=f"能说明 {student_input.topic} 的核心概念和使用场景。",
            activity=f"完成一个与 {student_input.topic} 直接相关的小案例并整理笔记。",
            check="提交案例结果并说明关键步骤。",
        )

    return KnowledgeMap(
        topic=student_input.topic,
        nodes=nodes,
        recommended_path=path,
    )
