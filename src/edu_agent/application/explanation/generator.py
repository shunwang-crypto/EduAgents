"""ExplanationGenerator：把 ExplanationContext + 教学目标 → 结构化 StepExplanation。

LLM 必须输出 schema 化的 blocks，禁止返回任意 Markdown 长文。
要求：每个 block 只解决一个教学目的；不生成练习/判题；不询问用户作答。
LLM 不可用时走 deterministic 降级（保证离线可用）。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import List, Optional

from edu_agent.application.explanation.context_builder import ExplanationContext
from edu_agent.application.explanation.models import (
    CODE_BLOCK_ORDER,
    THEORY_BLOCK_ORDER,
    BlockType,
    ExplanationBlock,
    StepExplanation,
)

logger = logging.getLogger("edu_agent.application.explanation.generator")

_SYSTEM = (
    "你不是在写教程文章。你正在为一个学习步骤生成结构化讲解。\n"
    "要求：\n"
    "1. 先整体后局部，每个 block 只解决一个教学目的；\n"
    "2. 复杂度逐步增加；\n"
    "3. 对编程内容优先使用代码拆解 / worked example；\n"
    "4. 避免重复定义，不生成与当前 KC 无关的百科知识；\n"
    "5. 不生成练习题、测试题、测验，不要求用户作答，不自动判分；\n"
    "6. 不要输出长篇连续 Markdown；每个 block 简短聚焦。\n"
    "只输出 JSON：{title, objective, blocks:[{type,title,content,data}]}，"
    "其中 type 必须属于：orientation,big_picture,concept,worked_example,"
    "code_walkthrough,contrast,misconception,application,recap,handoff。"
)


def _default_order(kc_category: str, kc_id: str) -> List[str]:
    cat = (kc_category or "").lower()
    coding = any(
        w in cat or w in kc_id.lower()
        for w in ("code", "program", "开发", "api", "cli", "编程", "app", "工程")
    )
    return CODE_BLOCK_ORDER if coding else THEORY_BLOCK_ORDER


def generate_explanation(
    ctx: ExplanationContext,
    explanation_id: Optional[str] = None,
    plan_id: str = "",
) -> StepExplanation:
    """生成结构化讲解。LLM 可用 → schema 输出；否则 deterministic 降级。"""
    exp_id = explanation_id or f"EXP-{uuid.uuid4().hex[:12]}"
    order = _default_order(ctx.kc_category, ctx.kc_id)

    # 离线 / 无 LLM 环境：跳过网络调用，直接用确定性讲解（避免挂起）。
    if _llm_disabled():
        return _assemble(ctx, exp_id, plan_id, _deterministic_blocks(ctx, order))

    try:
        blocks = _llm_blocks(ctx, order)
        if blocks:
            return _assemble(ctx, exp_id, plan_id, blocks)
    except Exception as exc:  # noqa: BLE001 - 任何 LLM 失败用确定性降级
        logger.warning("explanation LLM failed, using deterministic fallback: %s", exc)

    blocks = _deterministic_blocks(ctx, order)
    return _assemble(ctx, exp_id, plan_id, blocks)


def _llm_disabled() -> bool:
    """离线环境（EDU_OFFLINE）跳过 LLM 网络调用，直接用确定性讲解。

    在线生产环境仍走 LLM（若配置失败会由 ``_llm_blocks`` 内部异常降级）。
    """
    return os.environ.get("EDU_OFFLINE") in ("1", "true", "True")


def _assemble(
    ctx: ExplanationContext, exp_id: str, plan_id: str, blocks: List[ExplanationBlock]
) -> StepExplanation:
    return StepExplanation(
        explanation_id=exp_id,
        course_id=ctx.course_id,
        plan_id=plan_id,
        step_id="",  # 由 service 填
        kc_id=ctx.kc_id,
        schema_version=1,
        title=ctx.step_title or ctx.kc_title,
        objective=ctx.step_objective,
        estimated_minutes=ctx.step_minutes,
        blocks=blocks,
        context_hash=ctx.context_hash,
    )


def _llm_blocks(ctx: ExplanationContext, order: List[str]) -> List[ExplanationBlock]:
    from edu_agent.core.llm import get_kb_llm
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.utils.json import parse_json_markdown

    parser = JsonOutputParser()
    template = (
        "{system}\n\n{context}\n\n"
        "请按以下 block 顺序生成讲解（可省略不相关的 block，但保留 orientation 与 recap）：\n"
        "block 顺序建议：{order}\n"
        "输出 JSON（不要 Markdown 代码块包裹），形如：\n"
        "{{ \"title\": \"...\", \"objective\": \"...\", "
        "\"blocks\": [{{\"type\": \"concept\", \"title\": \"...\", \"content\": \"...\", \"data\": {{}}}}] }}"
    )
    prompt = ChatPromptTemplate.from_template(template)
    try:
        raw = (prompt | get_kb_llm(temperature=0.4)).invoke(
            {
                "system": _SYSTEM,
                "context": ctx.to_text(),
                "order": " → ".join(order),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("explanation LLM invoke failed: %s", exc)
        return []

    text = raw if isinstance(raw, str) else str(getattr(raw, "content", raw))
    if isinstance(raw, dict):
        text = str(raw)
    parsed = parse_json_markdown(text) if not isinstance(text, str) or not text.lstrip().startswith("{") else _parse(text)
    if not isinstance(parsed, dict):
        return []

    blocks: List[ExplanationBlock] = []
    for item in parsed.get("blocks") or []:
        if not isinstance(item, dict):
            continue
        btype = item.get("type")
        try:
            et = BlockType(btype)
        except ValueError:
            continue
        blocks.append(
            ExplanationBlock(
                type=et,
                title=str(item.get("title", "") or ""),
                content=str(item.get("content", "") or ""),
                data=item.get("data") or {},
                source_refs=list(item.get("source_refs") or []),
            )
        )
    return blocks


def _parse(text: str):
    import json
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        from langchain_core.utils.json import parse_json_markdown
        return parse_json_markdown(text)


def _deterministic_blocks(ctx: ExplanationContext, order: List[str]) -> List[ExplanationBlock]:
    """离线降级：从 context 确定性构造结构化讲解（无 LLM）。"""
    blocks: List[ExplanationBlock] = []
    prereq_str = "、".join(ctx.prerequisites) if ctx.prerequisites else "无直接前置"
    depend_str = "、".join(ctx.dependents) if ctx.dependents else "后续知识点"
    blocks.append(
        ExplanationBlock(
            type=BlockType.ORIENTATION,
            title="为什么现在学它？",
            content=(
                f"「{ctx.kc_title}」是「{ctx.goal}」路径上的关键知识点。"
                f"前置：{prereq_str}。它服务于：{depend_str}。"
                "理解它之后，后续知识点才真正有意义。"
            ),
        )
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.BIG_PICTURE,
            title="先看整体",
            data={"items": [ctx.kc_title, "→", *[d for d in ctx.dependents]] or [ctx.kc_title]},
        )
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.CONCEPT,
            title="核心概念",
            content=ctx.kc_description or f"掌握「{ctx.kc_title}」的核心思想与适用场景。",
        )
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.APPLICATION,
            title="它在项目中如何出现",
            content=f"「{ctx.kc_title}」常用于：{depend_str} 的实现与理解。",
        )
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.RECAP,
            title="你应该记住的 3 件事",
            data={"points": [
                f"「{ctx.kc_title}」是 {ctx.goal} 的一部分。",
                f"它的前置是：{prereq_str}。",
                f"它服务于：{depend_str}。",
            ]},
        )
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.HANDOFF,
            title="下一步",
            content="完成基础实践，验证你是否真正掌握该知识点。",
        )
    )
    return blocks
