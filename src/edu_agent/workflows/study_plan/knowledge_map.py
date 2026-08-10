import re
from typing import Iterable

from edu_agent.workflows.study_plan.schemas import (
    DecompositionResult,
    KnowledgeMap,
    KnowledgeNode,
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


def build_knowledge_map(
    student_input: StudentInput,
    decomposition: DecompositionResult,
) -> KnowledgeMap:
    """Build a stable, UI-friendly knowledge map without another LLM call."""

    nodes: list[KnowledgeNode] = []
    path: list[str] = []
    node_index = 1

    prerequisite_items = _unique_items(decomposition.prerequisite_concepts)
    core_items = _unique_items(decomposition.core_concepts)
    application_items = _unique_items(decomposition.application_directions)
    prerequisite_titles = [title for title, _ in prerequisite_items]
    core_titles = [title for title, _ in core_items]
    stages = decomposition.stage_suggestions or ["基础准备", "核心学习", "综合实践"]

    def add_node(
        title: str,
        summary: str,
        category: str,
        difficulty: str,
        minutes: int,
        stage: str,
        prerequisites: list[str],
        objective: str,
        application: str,
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
                stage=stage,
                learning_objective=objective,
                application_task=application,
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
            stage=_clean_title(stages[0]),
            prerequisites=[],
            objective=f"能用自己的话说明「{title}」并完成一个最小示例。",
            application=f"整理「{title}」的 3 条核心笔记，并完成一个最小应用案例。",
            check=f"不看资料解释「{title}」，并提交案例结果。",
        )

    for index, (title, summary) in enumerate(core_items):
        stage = _clean_title(stages[min(index + 1, len(stages) - 1)])
        add_node(
            title=title,
            summary=summary,
            category="核心知识",
            difficulty="中等",
            minutes=45,
            stage=stage,
            prerequisites=prerequisite_titles[:3],
            objective=f"能解释「{title}」的核心原理，并在学习目标场景中正确使用。",
            application=f"完成一个直接应用「{title}」的案例或计算任务。",
            check=f"提交案例结果，并说明「{title}」在其中解决了什么问题。",
        )

    for index, (title, summary) in enumerate(application_items):
        stage = _clean_title(stages[min(index + 1, len(stages) - 1)])
        add_node(
            title=title,
            summary=summary,
            category="实践应用",
            difficulty="实践",
            minutes=60,
            stage=stage,
            prerequisites=core_titles[:4],
            objective=f"独立完成「{title}」并留下可检查的学习产出。",
            application=summary,
            check="提交作品、关键步骤说明和一条复盘记录。",
        )

    if not nodes:
        add_node(
            title=student_input.topic,
            summary=f"围绕「{student_input.topic}」建立概念、方法和应用之间的联系。",
            category="核心知识",
            difficulty="入门",
            minutes=45,
            stage="核心学习",
            prerequisites=[],
            objective=f"能说明 {student_input.topic} 的核心概念和使用场景。",
            application=f"完成一个与 {student_input.topic} 直接相关的小案例。",
            check="提交案例结果并说明关键步骤。",
        )

    return KnowledgeMap(
        topic=student_input.topic,
        nodes=nodes,
        recommended_path=path,
    )
