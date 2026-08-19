import re
from math import floor
from typing import Dict, Iterable, List

from edu_agent.workflows.study_plan.canonicalizer import canonicalize_kc_id
from edu_agent.workflows.study_plan.schemas import (
    DecompositionResult,
    KnowledgeMap,
    KnowledgeNode,
    LearningStageSuggestion,
    STAGE_COUNT,
    StudentInput,
)


def _objective_for(title: str, category: str, content_type: str = "") -> str:
    """§18：按 category/content_type 生成 observable / KC-specific / actionable 学习目标。

    仅作为 ConceptSpec.learning_objective 缺失时的确定性 fallback；
    正式流程以 LLM 提供的 ConceptSpec.learning_objective 为准。
    """
    cat = (category or "").lower()
    ctype = (content_type or "").lower()
    t = title or "该知识点"
    if ctype in ("code",) or any(w in cat for w in ("code", "编程", "开发", "implementation")):
        return f"能够使用「{t}」完成基础实现，并解释关键调用和参数。"
    if ctype in ("theory",) or any(w in cat for w in ("theory", "数学", "线性代数", "微积分", "concept")):
        return f"能够解释「{t}」的核心关系，并说明它在目标任务中的作用。"
    if any(w in cat for w in ("prerequisite", "前置", "入门")):
        return f"能够说明「{t}」的基本概念与用途，并完成一个最小示例。"
    # mixed / 其它
    return f"能够解释「{t}」的核心原理，并完成一个基础实现流程。"


def _clean_title(value: str) -> str:
    max_length = 32
    value = re.sub(r"^[\d一二三四五六七八九十]+[.、：:]\s*", "", value.strip())
    value = re.sub(r"^(先|再|随后|最后)", "", value).strip()
    value = re.sub(r"^(系统)?(学习|理解|掌握|了解|熟悉)\s*", "", value).strip()
    for separator in ("：", ":"):
        if separator in value:
            prefix = value.split(separator, 1)[0].strip()
            if 2 <= len(prefix) <= 24:
                value = prefix
                break
    if len(value) > max_length:
        # 标题只保留主体，括号里的举例继续放在 summary；避免先按括号内逗号切开，
        # 产生「Python 类型注解语法（如 Optional」这类残缺标题。
        without_examples = re.sub(r"\s*[（(][^）)]*[）)]", "", value).strip()
        if len(without_examples) >= 2:
            value = without_examples
    if len(value) > max_length:
        value = re.split(
            r"[，；。]|并(?:完成|实现|使用|验证|说明)|以及|从而|以便|与(?=[A-Za-z\u4e00-\u9fff])",
            value,
            maxsplit=1,
        )[0].strip()
    if len(value) > max_length and "、" in value:
        value = value.split("、", 1)[0].strip()
    if len(value) > max_length:
        shortened = value[:max_length - 1].rstrip()
        # 最终硬截断也不能留下未闭合括号或书名号。
        for opener, closer in (("（", "）"), ("(", ")"), ("《", "》"), ("「", "」")):
            if shortened.count(opener) > shortened.count(closer):
                shortened = shortened[:shortened.rfind(opener)].rstrip()
        value = f"{shortened}…"
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


def _daily_minutes(value: str) -> int:
    """把 StudentInput.daily_time 解析成分钟；正式服务传入形如 ``20分钟``。"""
    text = (value or "").strip().lower()
    hour = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|hours?|h)", text)
    if hour:
        return max(1, round(float(hour.group(1)) * 60))
    minute = re.search(r"(\d+)\s*(?:分钟|minute|minutes|min)", text)
    if minute:
        return max(1, int(minute.group(1)))
    return 60


def _fit_nodes_to_budget(
    stage_nodes: list[list[KnowledgeNode]], student_input: StudentInput
) -> list[KnowledgeNode]:
    """保持三个阶段都有内容，同时让 UI 步骤总分钟数不超过用户预算。

    LLM 可能把主题拆成几十个概念。UI 如果不做最后一道确定性约束，就会出现
    "3 天 × 20 分钟，却生成 22 个、每个至少 30 分钟"的不可执行计划。
    这里把学习周期视为硬预算：优先每阶段保留一个节点，再按核心→基础→应用
    轮询补充；仅在原始建议总时长超预算时按权重缩放分钟数。
    """
    total_budget = max(
        STAGE_COUNT,
        int(student_input.days or 1) * _daily_minutes(student_input.daily_time),
    )
    total_nodes = sum(len(group) for group in stage_nodes)
    # 目标粒度约 20 分钟；最多 24 步，避免超长列表。三个阶段始终至少各一项。
    step_limit = min(total_nodes, max(STAGE_COUNT, min(24, total_budget // 20)))

    selected_by_stage: list[list[KnowledgeNode]] = [
        [group[0]] for group in stage_nodes
    ]
    cursors = [1, 1, 1]
    fill_order = [1, 0, 2]  # 核心知识优先，其次基础与综合应用
    selected_count = STAGE_COUNT
    while selected_count < step_limit:
        added = False
        for stage_index in fill_order:
            group = stage_nodes[stage_index]
            cursor = cursors[stage_index]
            if cursor < len(group):
                selected_by_stage[stage_index].append(group[cursor])
                cursors[stage_index] += 1
                selected_count += 1
                added = True
                if selected_count >= step_limit:
                    break
        if not added:
            break

    # 选点时可跨阶段轮询，但最终必须恢复阶段连续顺序，否则全局 seq 会出现
    # stage-1=1,4 / stage-2=2,5 这类跳号，破坏计划的一级结构。
    selected = [node for group in selected_by_stage for node in group]
    preferred = [node.estimated_minutes for node in selected]
    if sum(preferred) <= total_budget:
        allocated = preferred
    else:
        # 按原 30/45/60 权重缩放，使用最大余数法保证总和恰好等于预算。
        weight_sum = sum(preferred)
        raw = [total_budget * value / weight_sum for value in preferred]
        allocated = [max(1, floor(value)) for value in raw]
        remaining = total_budget - sum(allocated)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floor(raw[i]), reverse=True)
        for offset in range(remaining):
            allocated[order[offset % len(order)]] += 1

    # 截断后保留 canonical id（不再重排为 knowledge-N），仅更新预估分钟数。
    return [
        node.model_copy(update={"estimated_minutes": minutes})
        for node, minutes in zip(selected, allocated)
    ]


def build_knowledge_map(
    student_input: StudentInput,
    decomposition: DecompositionResult,
) -> KnowledgeMap:
    """Build a stable, UI-friendly knowledge map without another LLM call.

    结构化 decomposition：
    - graph edge 只来自 ``ConceptSpec.prerequisite_refs``（显式声明的依赖）；
    - Stage 只用于 Plan List grouping / schedule / presentation，不自动创造依赖；
    - canonical KC id 由 canonicalizer 统一派生；此处使用 ``temp_id`` 建立
      ``ConceptSpec → KnowledgeNode`` 的引用映射，并把 ``prerequisite_refs``
      解析为对应 prerequisite 节点的 canonical id。
    - 步骤数量与预计分钟数受 ``days × daily_time`` 硬预算约束。
    """

    stages = _normalize_stages(decomposition.stages)
    stage_by_order = {s.order: s for s in stages}
    concept_stage_of = {c.stage_order: stage_by_order.get(c.stage_order, stages[0]) for c in decomposition.concepts}

    def _node_id(c) -> str:
        # 生产流程用 temp_id 作为稳定 seed；canonicalizer 后续会把 temp_id
        # 映射为最终 canonical kc_id。这里直接派生，保证 id 稳定且可引用。
        return c.temp_id

    # 预建立 temp_id → KnowledgeNode，用于解析 prerequisite_refs。
    # 注意：edge 只在明确声明的前置之间生成。
    nodes_by_temp: Dict[str, KnowledgeNode] = {}
    # 先构造基础节点（无 prerequisites），再补 edge。
    prepared: List[KnowledgeNode] = []
    for concept in decomposition.concepts:
        stage = concept_stage_of[concept.stage_order]
        minutes = concept.estimated_minutes or _default_minutes(concept)
        raw_title = concept.title or concept.temp_id
        node = KnowledgeNode(
            id=_node_id(concept),
            # 对长/带动词前缀标题做确定性收敛，避免 UI 长标题撑坏节点
            # （结构化 ConceptSpec 已提供干净 title 时二次清洗是幂等的）。
            title=_clean_title(raw_title),
            # temp_id 作为 canonical_key 候选：合法则 canonicalizer 直接用
            # 有意义的 temp_id（numpy / linear_algebra）作为 canonical kc_id。
            canonical_key=concept.temp_id,
            category=_category_label(concept.category),
            summary=concept.summary or concept.title or "",
            prerequisites=[],  # 稍后按 prerequisite_refs 填充
            difficulty=_difficulty_label(concept.difficulty),
            estimated_minutes=minutes,
            stage_id=stage.stage_id,
            stage_title=stage.title,
            stage_order=stage.order,
            learning_objective=concept.learning_objective or _objective_for(
                concept.title or concept.temp_id, concept.category, concept.content_type
            ),
        )
        prepared.append(node)
        nodes_by_temp[concept.temp_id] = node

    # 建立 temp_id → canonical node.id 映射（temp_id 即 id）。
    temp_to_id = {c.temp_id: c.temp_id for c in decomposition.concepts}

    # 填充 prerequisites：只按显式 prerequisite_refs。
    for concept in decomposition.concepts:
        node = nodes_by_temp[concept.temp_id]
        prereq_ids: List[str] = []
        for ref in concept.prerequisite_refs or []:
            if ref in temp_to_id:
                prereq_ids.append(temp_to_id[ref])
        node.prerequisites = prereq_ids

    nodes = prepared
    if not nodes:
        # 空 decomposition 兜底：主题核心术语节点。
        fallback = KnowledgeNode(
            id=canonicalize_kc_id(f"{student_input.topic} 核心术语"),
            title=f"{student_input.topic} 核心术语与整体认识",
            category="核心知识",
            summary=f"掌握「{student_input.topic}」的核心术语、关键方法与主流程。",
            prerequisites=[],
            difficulty="中等",
            estimated_minutes=45,
            stage_id=stages[1].stage_id,
            stage_title=stages[1].title,
            stage_order=stages[1].order,
            learning_objective=_objective_for(student_input.topic, "core"),
        )
        nodes = [fallback]

    # 预算裁剪：保持结构，但按预算调整分钟数。
    # 每个阶段至少保留一个节点（旧行为：阶段缺失时兜底补默认节点）。
    grouped: List[List[KnowledgeNode]] = [[], [], []]
    for node in nodes:
        grouped[node.stage_order - 1].append(node)
    _fill_stage_fallbacks(grouped, student_input.topic, stages)
    nodes = _fit_nodes_to_budget(grouped, student_input)

    return KnowledgeMap(
        topic=student_input.topic,
        nodes=nodes,
        recommended_path=[n.id for n in nodes],
    )


def _fill_stage_fallbacks(
    grouped: List[List[KnowledgeNode]],
    topic: str,
    stages: List[LearningStageSuggestion],
) -> None:
    """为空阶段补充兜底节点（保持三阶段结构，避免 UI 空阶段）。"""
    defaults = [
        (f"{topic} 核心术语与整体认识", "前置知识",
         f"了解「{topic}」的核心术语、学习环境与整体知识结构。", "入门", 30),
        (f"{topic} 核心概念与主线方法", "核心知识",
         f"掌握「{topic}」的核心概念、关键方法与主流程。", "中等", 45),
        (f"{topic} 综合案例与知识总结", "实践应用",
         f"通过案例或小项目整合「{topic}」所学知识并输出总结。", "实践", 60),
    ]
    for idx, stage in enumerate(stages[:3]):
        if grouped[idx]:
            continue
        title, cat, summary, diff, minutes = defaults[idx]
        grouped[idx].append(KnowledgeNode(
            id=canonicalize_kc_id(title),
            title=title,
            category=cat,
            summary=summary,
            prerequisites=[],
            difficulty=diff,
            estimated_minutes=minutes,
            stage_id=stage.stage_id,
            stage_title=stage.title,
            stage_order=stage.order,
            learning_objective=_objective_for(topic, cat),
        ))


def _default_minutes(concept) -> int:
    """按分类给出确定性建议时长。"""
    return {"prerequisite": 30, "core": 45, "target": 60, "application": 60}.get(
        concept.category, 45
    )


def _category_label(category: str) -> str:
    return {
        "prerequisite": "前置知识",
        "core": "核心知识",
        "target": "核心知识",
        "application": "实践应用",
    }.get(category, "核心知识")


def _difficulty_label(difficulty: str) -> str:
    d = (difficulty or "").lower()
    if d in ("beginner", "easy", "入门"):
        return "入门"
    if d in ("advanced", "hard", "困难", "进阶"):
        return "进阶"
    return "中等"
