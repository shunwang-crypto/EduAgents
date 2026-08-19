"""Generate an adaptive explanation for one Knowledge Component.

The learning map owns sequencing and prerequisite reasoning. This module only
decides how to teach the selected KC. Block types are capabilities offered to
the model, never a fixed lesson template.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
import json
from dataclasses import dataclass
from typing import List, Optional, Sequence

from edu_agent.application.explanation.context_builder import ExplanationContext
from edu_agent.application.explanation.models import (
    EXPLANATION_BLOCK_CANDIDATES,
    BlockType,
    ExplanationBlock,
    StepExplanation,
)

logger = logging.getLogger("edu_agent.application.explanation.generator")


@dataclass(frozen=True)
class _LessonSection:
    """One model-designed chapter in a long-form explanation."""

    title: str
    purpose: str
    focus: str
    suggested_types: tuple[str, ...]
    target_chars: int


_PLANNING_MARKERS = (
    "为什么现在学",
    "知识网络中的位置",
    "学习路线",
    "当前路线",
    "前置知识",
    "它支撑什么",
    "后续知识",
    "与相邻知识点的关系",
)

_SYSTEM = (
    "你是 EduAgents 的知识讲解作者。你的唯一任务是把当前 Knowledge Component 教清楚。\n"
    "不要解释系统为什么推荐它，不介绍学习路径，不重复 prerequisite graph，也不要写“前置/后继/"
    "支撑关系”这类规划说明。正文从当前知识本身开始。\n"
    "先判断知识点的性质、学习目标、学习者需要理解到的深度，再自主设计最合适的教学结构。"
    "下面的 block type 只是可选能力池，不是模板，也不是必选项。不要为了富媒体强制生成代码、"
    "图片、公式、表格或图示。\n"
    "需要深度解释时，完整讲清概念、机制、条件、边界和例子；复杂知识点可以有几千字，没有固定"
    "字数和固定 section 数。worked_example 必须是真正完整的例子，而不是“你可以尝试……”的学习建议。"
    "diagram 必须表达当前知识内部的结构、过程或关系，而不是学习路线图。code 只在代码本身是"
    "理解知识的重要媒介时使用；formula 只在数学关系确实重要时使用；image 只在真实图片显著"
    "帮助理解时使用。所有 LaTeX 命令必须放在 $...$ 或 $$...$$ 数学分隔符内，不能把裸反斜杠"
    "命令直接写进普通段落。\n"
    "当 Trie、树、图或流程的结构本身有助于理解时，优先生成 diagram block，并用 "
    "data.nodes=[{id,label,...}] 与 data.edges=[{source,target,label}] 表达真实节点和关系；"
    "Trie 节点还要用 is_end 布尔字段明确终止状态。"
    "不要把 ASCII tree 当作普通 Markdown 文本输出；如果无法可靠给出结构化关系，宁可只写准确说明。"
    "Trie 的终止标记属于节点状态，不是新分支：已有 apple 后插入 app 时，不创建任何节点或分支，"
    "只把第二个 p 标记为单词结束，原有的 p -> l -> e 必须继续保留。\n"
    "不要生成练习题、测试题、测验、判题或要求用户作答。只输出当前请求明确指定的 JSON，"
    "不要添加 JSON 之外的说明。"
)


def _joined_context(ctx: ExplanationContext) -> str:
    return " ".join(
        (
            ctx.course_title,
            ctx.goal,
            ctx.kc_title,
            ctx.kc_description,
            ctx.step_objective,
            ctx.kc_category,
            ctx.preferred_style,
            " ".join(ctx.background_facts),
            " ".join(ctx.known_topics),
        )
    ).lower()


def _candidate_sections(ctx: ExplanationContext | str, kc_id: str = "") -> List[str]:
    """Return a context-sensitive optional capability pool.

    The string form is retained for small integrations that used the old
    private helper; normal generation always passes ``ExplanationContext``.
    """
    if isinstance(ctx, str):
        text = f"{ctx} {kc_id}".lower()
        category = text
        objective = ""
        sources = False
    else:
        text = _joined_context(ctx)
        category = (ctx.kc_category or "").lower()
        objective = (ctx.step_objective or "").lower()
        sources = bool(ctx.source_refs)

    def has(*words: str) -> bool:
        return any(word in text or word in category or word in objective for word in words)

    selected: List[str] = ["concept"]
    mathematical = has(
        "数学", "代数", "微积分", "导数", "梯度", "矩阵", "向量", "概率", "统计", "math", "mathematics",
        "公式", "证明", "推导", "calculus", "derivative", "gradient", "matrix", "probability",
    )
    programming_domain = has(
        "python", "编程", "代码", "程序", "code", "program", "api", "numpy", "pytorch", "sql",
        "javascript", "软件开发", "软件工程", "数据结构", "接口", "算法实现", "可运行",
    )
    implementation_goal = has("实现", "类", "方法", "运行", "调试")
    computer_context = has(
        "trie", "树", "字典", "递归", "算法", "模块", "框架", "张量", "数据库", "网络请求",
    )
    programming = programming_domain or (implementation_goal and computer_context)
    algorithm = has(
        "算法", "复杂度", "排序", "搜索", "图算法", "动态规划", "algorithm", "complexity",
        "recursion", "递归",
    )
    ai_system = has(
        "神经网络", "深度学习", "transformer", "attention", "cnn", "rnn", "rag", "模型",
        "架构", "系统", "数据流", "neural", "embedding",
    )
    humanities = has(
        "历史", "人物", "事件", "朝代", "战争", "history", "biography", "哲学", "文学",
    )
    operational = has(
        "安装", "配置", "部署", "命令", "工作流", "操作", "排错", "setup", "deploy", "workflow",
    )
    structural_knowledge = has(
        "trie", "前缀树", "树结构", "二叉树", "图结构", "图论", "tree structure", "graph structure",
    )

    def add(*names: str) -> None:
        for name in names:
            if name in EXPLANATION_BLOCK_CANDIDATES and name not in selected:
                selected.append(name)

    if mathematical:
        add("formula", "worked_example")
        if has("证明", "推导", "几何", "graph", "图形"):
            add("diagram")
    if programming:
        add("worked_example", "code_walkthrough", "misconception")
    if algorithm:
        add("big_picture", "diagram", "worked_example", "table", "misconception")
    if ai_system:
        add("big_picture", "diagram", "worked_example")
        if mathematical:
            add("formula")
    if humanities:
        add("big_picture", "contrast", "table", "worked_example")
    if operational:
        add("big_picture", "worked_example", "misconception", "table")
    if structural_knowledge:
        add("diagram")

    if not (mathematical or programming or algorithm or ai_system or humanities or operational):
        if len(text.strip()) > 100 or sources:
            add("worked_example")
    add("recap")
    return selected


def generate_explanation(
    ctx: ExplanationContext,
    explanation_id: Optional[str] = None,
    plan_id: str = "",
) -> StepExplanation:
    """Generate a structured explanation, with an evidence-honest fallback."""
    exp_id = explanation_id or f"EXP-{uuid.uuid4().hex[:12]}"
    candidates = _candidate_sections(ctx)

    if _llm_disabled():
        return _assemble(ctx, exp_id, plan_id, _deterministic_blocks(ctx))

    if _depth_requirements(ctx) != (0, 0):
        blocks = _generate_layered_blocks(ctx, candidates)
    else:
        blocks = _llm_blocks(ctx, candidates)
    if not blocks:
        raise RuntimeError("模型未返回可用的知识讲解内容，请稍后重新生成")
    blocks = _deduplicate_blocks([_normalize_block(block) for block in blocks])
    _validate_trie_prefix_diagrams(ctx, blocks)
    return _assemble(ctx, exp_id, plan_id, blocks)


def _explanation_chars(blocks: List[ExplanationBlock]) -> int:
    return sum(len(b.content or "") + len(str(b.data or {})) for b in blocks)


def _semantic_title_key(title: str) -> str:
    return re.sub(
        r"[\s\u3000()（）\[\]【】{}「」:：,，.!！？?、\-—_·]+",
        "",
        title.lower(),
    )


def _deduplicate_blocks(blocks: List[ExplanationBlock]) -> List[ExplanationBlock]:
    """Drop repeated section headings while keeping the first full content."""
    seen: set[tuple[BlockType, str]] = set()
    result: List[ExplanationBlock] = []
    for block in blocks:
        key = (block.type, _semantic_title_key(block.title))
        if key[1] and key in seen:
            continue
        if key[1]:
            seen.add(key)
        result.append(block)
    return result


def _depth_requirements(ctx: ExplanationContext) -> tuple[int, int]:
    text = _joined_context(ctx)
    complex_markers = (
        "数学", "微积分", "梯度", "算法", "复杂度", "神经网络", "深度学习",
        "transformer", "attention", "pytorch", "系统", "架构",
    )
    if any(marker in text for marker in complex_markers):
        # Chinese long-form lessons need several model calls: a single large
        # JSON response is easily truncated. This is a content budget, not a
        # reading-time conversion or a fixed template requirement.
        return 18_000, 26_000
    return 0, 0


def _generate_layered_blocks(
    ctx: ExplanationContext, candidates: Sequence[str]
) -> List[ExplanationBlock]:
    """Plan once, then generate each chapter once with shared context.

    The model first chooses a KC-specific teaching structure. Chapter calls
    receive that complete blueprint and compact continuity summaries, so they
    extend the same document without resending or rewriting the full lesson.
    """
    minimum_chars, target_chars = _depth_requirements(ctx)
    sections = _plan_lesson(ctx, candidates, minimum_chars, target_chars)
    if not sections:
        raise RuntimeError("模型未返回可用的讲解结构，请稍后重新生成")

    blueprint = "\n".join(
        f"{index}. {section.title}：{section.purpose}；重点：{section.focus}；"
        f"建议能力：{'、'.join(section.suggested_types) or '由内容决定'}；"
        f"目标约 {section.target_chars} 字符"
        for index, section in enumerate(sections, start=1)
    )
    all_blocks: List[ExplanationBlock] = []
    continuity: List[str] = []
    for section_index, section in enumerate(sections, start=1):
        previous = "\n".join(
            f"- {summary}" for summary in continuity[-8:]
        )
        generated, summary = _llm_section(
            ctx,
            candidates,
            section=section,
            section_index=section_index,
            section_count=len(sections),
            blueprint=blueprint,
            previous_summaries=previous or "（这是第一章）",
        )
        if not generated:
            raise RuntimeError(f"模型未生成讲解章节：{section.title}")
        for block in generated:
            if not any(
                block.title.strip() == existing.title.strip()
                and block.type == existing.type
                for existing in all_blocks
            ):
                all_blocks.append(block)
        continuity.append(summary or _summarize_generated_section(section, generated))

    if _explanation_chars(all_blocks) < minimum_chars:
        logger.warning(
            "long-form explanation below requested depth: got=%s minimum=%s kc=%s",
            _explanation_chars(all_blocks),
            minimum_chars,
            ctx.kc_id,
        )
    return all_blocks


def _plan_lesson(
    ctx: ExplanationContext,
    candidates: Sequence[str],
    minimum_chars: int,
    target_chars: int,
) -> List[_LessonSection]:
    """Ask the model for a knowledge-specific blueprint, not a stock outline."""
    prompt = (
        f"{_SYSTEM}\n\n"
        f"当前知识上下文：\n{ctx.to_text()}\n\n"
        f"可选能力池：{'、'.join(candidates)}\n"
        "先只设计完整讲解的章节蓝图，不写正文。章节由当前知识的性质决定，不能套固定的"
        "编程/理论模板。各章必须互不重复，并共同覆盖：它是什么、为什么这样工作、至少一个"
        "完整具体例子，以及需要时的条件、边界和误区。不要加入学习路线、推荐原因、练习题。\n"
        f"整篇正文最低约 {minimum_chars} 字符，目标约 {target_chars} 字符。请把预算合理分配"
        "到适合这个知识点的章节中（通常 3 至 10 章）；不要为了凑章节拆碎内容。复杂机制和"
        "完整例子的预算应明显高于 recap。\n"
        "只输出 JSON："
        '{"sections":[{"title":"...","purpose":"...","focus":"...",'
        '"suggested_types":["concept"],"target_chars":4000}]}'
    )
    parsed = _invoke_json(prompt, temperature=0.2)
    sections: List[_LessonSection] = []
    for item in parsed.get("sections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        purpose = str(item.get("purpose") or "").strip()
        focus = str(item.get("focus") or "").strip()
        if not title or not purpose or any(marker in title for marker in _PLANNING_MARKERS):
            continue
        types = tuple(
            name for name in item.get("suggested_types") or []
            if name in candidates
        )
        try:
            budget = int(item.get("target_chars") or 0)
        except (TypeError, ValueError):
            budget = 0
        sections.append(
            _LessonSection(
                title=title,
                purpose=purpose,
                focus=focus,
                suggested_types=types,
                target_chars=max(2200, min(budget or 3500, 9000)),
            )
        )
    if not 3 <= len(sections) <= 10:
        return []

    assigned = sum(section.target_chars for section in sections)
    if assigned < target_chars:
        extra_each = (target_chars - assigned + len(sections) - 1) // len(sections)
        sections = [
            _LessonSection(
                title=section.title,
                purpose=section.purpose,
                focus=section.focus,
                suggested_types=section.suggested_types,
                target_chars=min(9000, section.target_chars + extra_each),
            )
            for section in sections
        ]
    return sections


def _llm_section(
    ctx: ExplanationContext,
    candidates: Sequence[str],
    *,
    section: _LessonSection,
    section_index: int,
    section_count: int,
    blueprint: str,
    previous_summaries: str,
) -> tuple[List[ExplanationBlock], str]:
    suggested = "、".join(section.suggested_types) or "由内容决定"
    prompt = (
        f"{_SYSTEM}\n\n"
        f"当前知识上下文（每章共享的事实边界）：\n{ctx.to_text()}\n\n"
        f"整篇讲解蓝图：\n{blueprint}\n\n"
        f"已完成章节的连续性摘要：\n{previous_summaries}\n\n"
        f"现在只生成第 {section_index}/{section_count} 章《{section.title}》。\n"
        f"本章目的：{section.purpose}\n本章重点：{section.focus}\n"
        f"建议能力：{suggested}\n本章正文目标约 {section.target_chars} 字符。\n"
        "必须写成可直接阅读的深入教学正文，充分展开因果、步骤和具体细节，不要写成提纲。"
        "不要复述其他章节；需要承接时直接使用连续性摘要中的结论。若本章负责例子，必须从"
        "问题或输入完整走到结果，并展示关键中间过程。block type 仍按实际内容选择。\n"
        "只输出 JSON："
        '{"blocks":[{"type":"concept","title":"...","content":"...",'
        '"data":{},"source_refs":[]}],"continuity_summary":"用 2 至 5 句记录本章已确立的关键结论，供下一章承接"}'
    )
    parsed = _invoke_json(prompt, temperature=0.4)
    return _blocks_from_payload(parsed), str(parsed.get("continuity_summary") or "").strip()


def _summarize_generated_section(
    section: _LessonSection, blocks: Sequence[ExplanationBlock]
) -> str:
    titles = "、".join(block.title for block in blocks)
    return f"《{section.title}》已讲清：{section.focus}。包含：{titles}。"


def _invoke_json(prompt: str, *, temperature: float) -> dict:
    """Invoke one bounded generation step and normalize Gemini JSON output."""
    from edu_agent.core.agent_runner import _strip_model_thought
    from edu_agent.core.llm import get_kb_llm
    from langchain_core.utils.json import parse_json_markdown

    raw = get_kb_llm(temperature=temperature, max_tokens=8192).invoke(prompt)
    if isinstance(raw, dict):
        return raw
    text = raw if isinstance(raw, str) else str(getattr(raw, "content", raw))
    parsed = _parse(_strip_model_thought(text), parse_json_markdown)
    return parsed if isinstance(parsed, dict) else {}


def _blocks_from_payload(parsed: dict) -> List[ExplanationBlock]:
    blocks: List[ExplanationBlock] = []
    for item in parsed.get("blocks") or []:
        if not isinstance(item, dict):
            continue
        try:
            et = BlockType(item.get("type"))
        except (TypeError, ValueError):
            continue
        title = str(item.get("title", "") or "").strip()
        content = str(item.get("content", "") or "")
        if et in {BlockType.ORIENTATION, BlockType.HANDOFF}:
            continue
        if not title or any(marker in title for marker in _PLANNING_MARKERS):
            continue
        if any(marker in content for marker in _PLANNING_MARKERS):
            continue
        blocks.append(
            ExplanationBlock(
                type=et,
                title=title,
                content=content,
                data=item.get("data") or {},
                source_refs=list(item.get("source_refs") or []),
            )
        )
    return blocks


def _normalize_block(block: ExplanationBlock) -> ExplanationBlock:
    block.content = _normalize_latex_markdown(block.content)
    if block.type == BlockType.CODE_WALKTHROUGH:
        _extract_code_walkthrough(block)
    if block.type == BlockType.DIAGRAM:
        _extract_ascii_tree(block)
    if block.type == BlockType.FORMULA:
        formula = block.data.get("formula")
        if not block.data.get("latex") and isinstance(formula, str):
            block.data["latex"] = formula
    if isinstance(block.data.get("explanation"), str):
        block.data["explanation"] = _normalize_latex_markdown(block.data["explanation"])
    return block


def _extract_ascii_tree(block: ExplanationBlock) -> None:
    """Convert a generated ASCII Trie/tree into structured diagram data."""
    if block.data.get("nodes") and block.data.get("edges"):
        return
    content = re.sub(r"\\n", "\n", block.content or "")
    if not re.search(r"(?:^|\n)\s*root\b|(?:^|\n)\s*[├└]──", content):
        return
    token_re = re.compile(
        r"(?P<branch>[├└]──)?\s*['\"](?P<label>[^'\"]+)['\"]"
        r"\s*\(\s*is_end(?:_of_word)?\s*:\s*(?P<end>True|False)\s*\)"
    )
    nodes: list[dict] = [{"id": "root", "label": "root"}]
    edges: list[dict] = []
    stack: list[tuple[int, str]] = [(-1, "root")]
    node_number = 0
    tree_lines: list[str] = []
    for line in content.splitlines():
        if not re.search(r"root\b|[├└]──", line):
            continue
        matches = list(token_re.finditer(line))
        if line.lstrip().startswith("root"):
            tree_lines.append(line)
            continue
        for match in matches:
            marker_start = match.start("branch") if match.group("branch") else match.start()
            indent = len(line[:marker_start].expandtabs(4))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else "root"
            node_number += 1
            node_id = f"tree-{node_number}"
            label = f"{match.group('label')} (is_end: {match.group('end')})"
            nodes.append({"id": node_id, "label": label, "is_end": match.group("end") == "True"})
            edges.append({"source": parent, "target": node_id, "label": match.group("label")})
            stack.append((indent, node_id))
        tree_lines.append(line)
    if len(nodes) <= 1 or len(edges) != len(nodes) - 1:
        return
    block.data["nodes"] = nodes
    block.data["edges"] = edges
    block.data["diagram_type"] = "tree"
    tree_text = "\n".join(tree_lines)
    block.content = content.replace(tree_text, "").strip()


def _validate_trie_prefix_diagrams(
    ctx: ExplanationContext, blocks: Sequence[ExplanationBlock]
) -> None:
    """Reject the known app/apple Trie corruption instead of displaying it."""
    context = _joined_context(ctx)
    if "trie" not in context and "前缀树" not in context:
        return
    exact_app = re.compile(r"(?<![A-Za-z])app(?![A-Za-z])", re.IGNORECASE)
    for block in blocks:
        title = block.title.lower()
        if block.type != BlockType.DIAGRAM or not exact_app.search(title):
            continue
        if block.data.get("diagram_type") != "tree" and not any(
            marker in title for marker in ("trie", "树", "结构")
        ):
            continue
        nodes = block.data.get("nodes")
        edges = block.data.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise RuntimeError("Trie 的 app 插入图缺少结构化 nodes/edges")
        by_id = {
            str(node.get("id")): node
            for node in nodes
            if isinstance(node, dict) and node.get("id") is not None
        }
        outgoing: dict[str, list[str]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source and target in by_id:
                outgoing.setdefault(source, []).append(target)

        def node_token(node_id: str) -> str:
            node = by_id.get(node_id, {})
            label = str(node.get("label") or node.get("name") or "").strip()
            quoted = re.match(r"^['\"]([^'\"]+)['\"]", label)
            if quoted:
                return quoted.group(1).lower()
            return label.split(" ", 1)[0].strip("'\"").lower()

        roots = [node_id for node_id in by_id if node_token(node_id) == "root"]
        current = roots[0] if roots else ""
        path: list[str] = []
        for expected in ("a", "p", "p", "l", "e"):
            matches = [
                target for target in outgoing.get(current, [])
                if node_token(target) == expected
            ]
            if not matches:
                raise RuntimeError(
                    "Trie 语义校验失败：已有 apple 后插入 app 必须保留 a-p-p-l-e 路径"
                )
            current = matches[0]
            path.append(current)
        terminal_node = by_id[path[2]]
        terminal = terminal_node.get(
            "is_end",
            terminal_node.get("is_end_of_word", terminal_node.get("is_terminal")),
        )
        if terminal is not True:
            raise RuntimeError(
                "Trie 语义校验失败：插入 app 后第二个 p 必须标记为单词结束"
            )


def _extract_code_walkthrough(block: ExplanationBlock) -> None:
    """Promote fenced code into the structured field used by the frontend.

    Gemini often follows the teaching request and emits a real
    ``code_walkthrough`` block, but puts the code in Markdown instead of
    ``data.code``. That is still useful content; normalize it into the
    dedicated renderer without asking the model to regenerate the lesson.
    """
    if isinstance(block.data.get("code"), str) and block.data["code"].strip():
        return
    match = re.search(r"```(?:[A-Za-z0-9_+#.-]+)?[ \t]*\n?(.*?)```", block.content, re.DOTALL)
    if not match:
        return
    code = match.group(1)
    # Provider JSON sometimes preserves Markdown line breaks as visible
    # ``\\n``. In a code field these are formatting escapes, not Python text.
    code = re.sub(r"\\n", "\n", code).strip("\n")
    if code:
        block.data["code"] = code
        block.content = (block.content[:match.start()] + block.content[match.end():]).strip()


def _normalize_latex_markdown(text: str) -> str:
    """Put common bare LaTeX runs into remark-math delimiters."""
    if not text or "\\" not in text:
        return text
    # Some OpenAI-compatible models double-escape Markdown newlines as the
    # two visible characters ``\\n``. Restore those paragraph breaks while
    # preserving LaTeX commands such as ``\\nabla``.
    text = re.sub(r"\\n(?![A-Za-z])", "\n", text)
    commands = r"nabla|frac|partial|begin|end|theta|eta|cdot|sum|infty|rightarrow|left|right"
    pattern = re.compile(
        rf"(\\begin\{{[^}}]+\}}.*?\\end\{{[^}}]+\}}|\\(?:{commands})[^。！？\n]*)",
        re.DOTALL,
    )
    # Preserve already delimited inline/display math and only repair prose
    # segments outside them.
    parts = re.split(r"(\$\$.*?\$\$|\$[^$\n]*\$)", text, flags=re.DOTALL)
    for index in range(0, len(parts), 2):
        parts[index] = pattern.sub(lambda m: f"$${m.group(1).strip()}$$", parts[index])
    return "".join(parts)


def _llm_disabled() -> bool:
    return os.environ.get("EDU_OFFLINE") in ("1", "true", "True")


def _assemble(
    ctx: ExplanationContext, exp_id: str, plan_id: str, blocks: List[ExplanationBlock]
) -> StepExplanation:
    return StepExplanation(
        explanation_id=exp_id,
        course_id=ctx.course_id,
        plan_id=plan_id,
        step_id="",  # service fills the concrete PlanStep id
        kc_id=ctx.kc_id,
        schema_version=2,
        title=_safe_title(ctx),
        objective=ctx.step_objective,
        estimated_minutes=ctx.step_minutes,
        blocks=blocks,
        context_hash=ctx.context_hash,
    )


def _llm_blocks(
    ctx: ExplanationContext,
    candidates: Sequence[str],
    depth_instruction: str = "",
) -> List[ExplanationBlock]:
    from edu_agent.core.llm import get_kb_llm
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.utils.json import parse_json_markdown

    template = (
        "{system}\n\n当前知识上下文（不含 prerequisite graph）：\n{context}\n\n"
        "可选能力池（按需选择、可以全部不用，也可以合并）：{candidates}\n"
        "不要创建规划说明 section；再次检查内容是否真正解释了当前知识的机制、边界和具体例子。"
        "\n{depth_instruction}\n"
        "输出 JSON（不要 Markdown 代码块包裹），形如：\n"
        "{{\"title\":\"...\",\"objective\":\"...\","
        "\"blocks\":[{{\"type\":\"concept\",\"title\":\"...\","
        "\"content\":\"...\",\"data\":{{}},\"source_refs\":[]}}]}}"
    )
    prompt = ChatPromptTemplate.from_template(template)
    raw = (prompt | get_kb_llm(temperature=0.4)).invoke(
        {
            "system": _SYSTEM,
                "context": ctx.to_text(),
                "candidates": "、".join(candidates),
                "depth_instruction": depth_instruction,
        }
    )

    text = raw if isinstance(raw, str) else str(getattr(raw, "content", raw))
    if isinstance(raw, dict):
        text = str(raw)
    # Gemini's OpenAI-compatible adapter may put reasoning before the JSON.
    # Remove it before parse_json_markdown; otherwise a valid lesson is
    # discarded as if the model had returned malformed output.
    from edu_agent.core.agent_runner import _strip_model_thought

    text = _strip_model_thought(text)
    parsed = _parse(text, parse_json_markdown)
    if not isinstance(parsed, dict):
        return []

    return _blocks_from_payload(parsed)


def _parse(text: str, parse_json_markdown=None):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        repaired = _escape_model_json_backslashes(text)
        try:
            return json.loads(repaired)
        except Exception:  # noqa: BLE001
            if parse_json_markdown is not None:
                return parse_json_markdown(repaired)
        from langchain_core.utils.json import parse_json_markdown as parser
        return parser(repaired)


def _escape_model_json_backslashes(text: str) -> str:
    """Escape non-JSON backslashes inside strings without corrupting LaTeX.

    Models commonly put ``\\nabla``, ``\\(``, or ``\\%`` directly in JSON.
    Some LaTeX commands begin with a character that is technically a JSON
    escape, so the scanner recognizes complete alphabetic commands rather
    than silently turning them into control characters.
    """
    result: List[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            in_string = not in_string
            result.append(char)
            index += 1
            continue
        if not in_string or char != "\\":
            result.append(char)
            index += 1
            continue

        if index + 1 >= length:
            result.append("\\\\")
            index += 1
            continue

        following = text[index + 1]
        if following == "u":
            codepoint = text[index + 2:index + 6]
            if len(codepoint) == 4 and all(
                char in "0123456789abcdefABCDEF" for char in codepoint
            ):
                result.extend(("\\", "u", codepoint))
                index += 6
                continue
        if following in {'"', "\\", "/"}:
            result.extend(("\\", following))
            index += 2
            continue
        if following in "bfnrt" and (
            index + 2 >= length or not text[index + 2].isalpha()
        ):
            result.extend(("\\", following))
            index += 2
            continue

        # Preserve the original textual slash by encoding it as ``\\``.
        result.extend(("\\", "\\", following))
        index += 2
    return "".join(result)


def _is_placeholder_description(ctx: ExplanationContext, description: str) -> bool:
    normalized = " ".join(description.lower().split())
    title = " ".join(ctx.kc_title.lower().split())
    return normalized in {
        f"{title} 描述",
        f"{title} 简介",
        f"{title} description",
        "根据学习主题补充必要基础知识",
    }


def _safe_title(ctx: ExplanationContext) -> str:
    for candidate in (ctx.step_title, ctx.kc_title):
        title = (candidate or "").strip()
        if not title:
            continue
        if "根据学习主题补充必要基础知识" in title:
            continue
        if any(marker in title for marker in _PLANNING_MARKERS):
            continue
        return title
    return "学习讲解"


def _deterministic_blocks(ctx: ExplanationContext) -> List[ExplanationBlock]:
    """Evidence-honest offline fallback.

    No route, code, formula, example, or domain facts are invented. A real
    description is shown as a concise concept block; absent evidence produces
    an explicit degraded state for model retry.
    """
    description = (ctx.kc_description or "").strip()
    objective = (ctx.step_objective or "").strip()
    if not description or _is_placeholder_description(ctx, description):
        content = (
            "当前环境无法生成这项知识的完整讲解，因为没有可用的知识描述或课程资料。"
            "请在模型和课程资料可用时重新打开本节。"
        )
        if objective:
            content += f"\n\n本节目标：{objective}"
        return [
            ExplanationBlock(
                type=BlockType.CONCEPT,
                title="讲解暂不可用",
                content=content,
                source_refs=list(ctx.source_refs[:3]),
            )
        ]

    content = description
    if objective:
        content += f"\n\n**本节目标**：{objective}"
    return [
        ExplanationBlock(
            type=BlockType.CONCEPT,
            title=_safe_title(ctx),
            content=content,
            source_refs=list(ctx.source_refs[:3]),
        )
    ]
