"""ExplanationGenerator：生成 Adaptive Rich Explanation（Rich Learning Document）。

LLM 输出可渲染的 blocks，但 block 数量、正文长度和 section 选择都由
知识点复杂度、学习目标、学习者背景、内容类别和资料来源决定：简单知识点
可以只有几个短 section，复杂知识点写几千字、十几个 section 也是合法的。
schema 描述渲染方式，不限制正文长度，也不规定固定模板。
LLM 不可用时走 deterministic 降级（保证离线可用）。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import List, Optional

from edu_agent.application.explanation.context_builder import ExplanationContext
from edu_agent.application.explanation.models import (
    CODE_BLOCK_CANDIDATES,
    THEORY_BLOCK_CANDIDATES,
    BlockType,
    ExplanationBlock,
    StepExplanation,
)

logger = logging.getLogger("edu_agent.application.explanation.generator")

_SYSTEM = (
    "你是 EduAgents 的 Adaptive Rich Explanation 教学作者。\n"
    "请为一个知识点写一篇可直接阅读的完整学习文档（Rich Learning Document），"
    "读者读完这一篇就能真正学会这个知识点，不需要再去别处补课。\n"
    "篇幅：没有字数上下限，也没有固定段数。简单知识点可以短；复杂知识点"
    "（如 Self-Attention、RAG、CNN、反向传播）写几千字完全正常。"
    "严禁把每个 section 写成一两句话的提纲式摘要——那不是讲解，是目录。"
    "每个 section 都要写到能自圆其说：给出机制、原因、条件、边界，并在需要时举例子、"
    "列步骤、画结构、写公式或贴代码。\n"
    "结构：必须结构化，但不要套固定模板。根据知识点复杂度、学习目标、学习者背景、"
    "内容类别和资料来源，自主选择、排序、增删 section。先建立 mental model，"
    "再按需要展开原理、公式、流程/架构图、案例、代码与逐行解释、对比表、常见误区、"
    "实际应用和总结。不同知识点应该长出不同的结构。\n"
    "编程知识优先加入可运行代码（code_walkthrough.data.code）与逐行注解；"
    "理论知识优先加入图示（diagram）、公式（formula）、对比（contrast/table）和 worked_example。\n"
    "图示：优先用结构化 diagram —— data.nodes 为 [{id,label}]，data.edges 为 "
    "[{source,target,label}]，前端会自动分层渲染成流程图/结构图。"
    "只有确实存在真实图片资料时才使用 image block；不要为了装饰给每个知识点硬造图片。\n"
    "content 是不受限的 Markdown，可用标题、列表、表格、fenced code 和 LaTeX。\n"
    "不要生成练习题、测试题、测验、判题或要求用户作答。\n"
    "只输出 JSON：{title, objective, blocks:[{type,title,content,data,source_refs}]}。"
    "type 可用：orientation,big_picture,concept,worked_example,code_walkthrough,contrast,"
    "misconception,application,recap,handoff,diagram,image,table,formula。"
)


def _candidate_sections(kc_category: str, kc_id: str) -> List[str]:
    """按内容类别给出候选 section 池（候选，不是固定模板 / 固定顺序）。"""
    cat = (kc_category or "").lower()
    coding = any(
        w in cat or w in kc_id.lower()
        for w in ("code", "program", "开发", "api", "cli", "编程", "app", "工程")
    )
    return CODE_BLOCK_CANDIDATES if coding else THEORY_BLOCK_CANDIDATES


def generate_explanation(
    ctx: ExplanationContext,
    explanation_id: Optional[str] = None,
    plan_id: str = "",
) -> StepExplanation:
    """生成结构化讲解。LLM 可用 → schema 输出；否则 deterministic 降级。"""
    exp_id = explanation_id or f"EXP-{uuid.uuid4().hex[:12]}"
    candidates = _candidate_sections(ctx.kc_category, ctx.kc_id)

    # 离线 / 无 LLM 环境：跳过网络调用，直接用确定性讲解（避免挂起）。
    if _llm_disabled():
        return _assemble(ctx, exp_id, plan_id, _deterministic_blocks(ctx, candidates))

    try:
        blocks = _llm_blocks(ctx, candidates)
        if blocks:
            return _assemble(ctx, exp_id, plan_id, blocks)
    except Exception as exc:  # noqa: BLE001 - 任何 LLM 失败用确定性降级
        logger.warning("explanation LLM failed, using deterministic fallback: %s", exc)

    blocks = _deterministic_blocks(ctx, candidates)
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
        schema_version=2,
        title=ctx.step_title or ctx.kc_title,
        objective=ctx.step_objective,
        estimated_minutes=ctx.step_minutes,
        blocks=blocks,
        context_hash=ctx.context_hash,
    )


def _llm_blocks(ctx: ExplanationContext, candidates: List[str]) -> List[ExplanationBlock]:
    from edu_agent.core.llm import get_kb_llm
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.utils.json import parse_json_markdown

    parser = JsonOutputParser()
    template = (
        "{system}\n\n{context}\n\n"
        "以下只是与内容类别相关的候选 section，不是固定模板、也不是必须全部使用："
        "可以省略、合并、增加（diagram / image / table / formula / contrast），"
        "并按教学逻辑自行排序：\n{candidates}\n"
        "再次强调：不要写成每段两三句话的提纲，把该讲清楚的机制、条件和例子写足。\n"
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
                "candidates": "、".join(candidates),
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


def _deterministic_blocks(
    ctx: ExplanationContext, candidates: List[str]
) -> List[ExplanationBlock]:
    """离线降级：从 context 确定性构造结构化讲解（无 LLM）。

    只使用 context 里真实存在的信息（知识点描述、目标、前置/后继、资料来源）与
    通用学习方法，绝不编造这个知识点的具体事实、数字或代码。
    §40：可见文本一律使用人类可读 title，绝不出现内部 id。
    """
    blocks: List[ExplanationBlock] = []
    coding = "code_walkthrough" in candidates
    pres = ctx.prerequisite_titles
    deps = ctx.dependent_titles
    prereq_str = "、".join(pres) if pres else "无直接前置"
    depend_str = "、".join(deps) if deps else "后续知识点"
    goal_str = ctx.goal or "当前学习目标"
    objective = ctx.step_objective or f"能用自己的话解释「{ctx.kc_title}」并把它用起来"
    difficulty_note = {
        "easy": "这个知识点难度不高，重点是把概念用准确的语言说清楚，不要停留在“看懂了”。",
        "hard": "这个知识点难度较高，建议分两次阅读：第一次抓主干，第二次再补细节和边界条件。",
    }.get((ctx.kc_difficulty or "").lower(), "这个知识点难度中等，先抓主干，再逐步补上细节和边界条件。")

    blocks.append(
        ExplanationBlock(
            type=BlockType.ORIENTATION,
            title="为什么现在学它？",
            content=(
                f"「{ctx.kc_title}」是「{goal_str}」路径上的关键知识点。\n\n"
                f"- **本节目标**：{objective}\n"
                f"- **需要的前置**：{prereq_str}\n"
                f"- **它支撑什么**：{depend_str}\n\n"
                f"{difficulty_note}\n\n"
                "读这一节时带着三个问题：它解决什么问题、它靠什么机制解决、"
                "什么情况下它不适用。这三个问题回答清楚了，后面的知识点才真正有意义。"
            ),
        )
    )

    # 结构化图示优先（不强制图片）：把它在知识网络中的位置画成流程图
    diagram_nodes = [{"id": t, "label": t} for t in [*pres, ctx.kc_title, *deps]]
    diagram_edges = [{"source": t, "target": ctx.kc_title, "label": "前置"} for t in pres]
    diagram_edges += [{"source": ctx.kc_title, "target": t, "label": "支撑"} for t in deps]
    if diagram_edges:
        blocks.append(
            ExplanationBlock(
                type=BlockType.DIAGRAM,
                title="它在知识网络中的位置",
                content="左侧是必须先具备的基础，右侧是学完之后能继续推进的方向。",
                data={"nodes": diagram_nodes, "edges": diagram_edges},
            )
        )
    else:
        blocks.append(
            ExplanationBlock(
                type=BlockType.BIG_PICTURE,
                title="先看整体",
                content=f"「{ctx.kc_title}」在本课程中相对独立，可以直接开始。",
                data={"items": [ctx.kc_title, *deps]},
            )
        )

    blocks.append(
        ExplanationBlock(
            type=BlockType.CONCEPT,
            title="核心概念与 mental model",
            content=(
                (ctx.kc_description + "\n\n") if ctx.kc_description else ""
            )
            + (
                f"要建立「{ctx.kc_title}」的 mental model，先把它拆成三段来看：\n\n"
                "1. **输入**：它接收什么？这些输入必须满足哪些前提（格式、范围、假设）？\n"
                "2. **关键变换**：中间到底发生了什么？把这一步用一句话讲清楚，"
                "再展开成可以逐步观察的小步骤——这是理解的核心，也是最容易被跳过的地方。\n"
                "3. **输出**：得到什么结果？结果怎么验证是对的？\n\n"
                f"然后再补上**边界条件**：它在什么前提下成立、什么情况下会失效。"
                f"具备 {prereq_str} 这些基础之后，这里的每一步都应该能自己复述出来；"
                f"能复述，才说明模型建立起来了，而不是记住了一个名字。\n\n"
                f"最后把它放回上下文：它向前依赖 {prereq_str}，向后连接 {depend_str}。"
                "理解这些关系，比背诵定义有用得多。"
            ),
            source_refs=list(ctx.source_refs[:3]),
        )
    )

    # 关系表：只用图谱里真实存在的信息，不编造
    if pres or deps:
        rows = [[t, "前置", f"缺了它，「{ctx.kc_title}」的前提假设就不成立"] for t in pres]
        rows += [[t, "后继", f"它建立在「{ctx.kc_title}」之上，学完可以直接推进"] for t in deps]
        blocks.append(
            ExplanationBlock(
                type=BlockType.TABLE,
                title="与相邻知识点的关系",
                content="把相邻知识点的角色分清楚，可以避免把不同层次的问题混在一起。",
                data={"headers": ["知识点", "角色", "为什么相关"], "rows": rows},
            )
        )

    example_steps = (
        [
            "准备最小可运行环境，只保留和这个知识点直接相关的部分。",
            "写出最小示例：输入尽量小，能一眼看出输出对不对。",
            "逐行读一遍自己写的代码，说明每一行为什么必须存在。",
            "故意改坏一个地方（改参数、去掉一步），观察结果怎么变——这一步最能暴露理解漏洞。",
            "恢复正确版本，把它整理成以后可以直接复用的片段。",
        ]
        if coding
        else [
            "用一句话写下它解决的问题，不要用课程原文的措辞。",
            "从最简单的情形开始，手推一遍完整过程并记录中间结果。",
            "换一组不同的输入再推一遍，观察哪些结论变了、哪些没变。",
            "找一个反例：什么情况下这个方法不成立？为什么？",
            "把整个过程压缩成三到五句话，能讲给别人听就算过关。",
        ]
    )
    blocks.append(
        ExplanationBlock(
            type=BlockType.WORKED_EXAMPLE,
            title="怎么动手把它学会",
            content=(
                f"理解「{ctx.kc_title}」不能只靠读。按下面的顺序走一遍，"
                "每一步都要有可以看见的中间结果："
            ),
            data={"steps": example_steps},
        )
    )

    misconception_extra = ""
    if ctx.misconceptions:
        misconception_extra = "\n\n结合你之前的学习记录，特别留意：" + "；".join(
            ctx.misconceptions[:3]
        )
    blocks.append(
        ExplanationBlock(
            type=BlockType.MISCONCEPTION,
            title="易混淆点",
            content=(
                "常见误区通常不是术语记错，而是忽略适用条件。\n\n"
                f"- **和相邻概念混为一谈**：先分清「{ctx.kc_title}」解决的问题"
                f"和 {depend_str} 解决的问题分别是什么，两者的边界在哪里。\n"
                "- **把相关当成因果**：看到两件事一起出现，就认为一个导致另一个。"
                "用一个反例检验自己的结论。\n"
                "- **只记结论不记条件**：结论离开前提就不成立，记住结论的同时一定要记住它成立的范围。"
                + misconception_extra
            ),
        )
    )

    blocks.append(
        ExplanationBlock(
            type=BlockType.APPLICATION,
            title="实际应用",
            content=(
                f"在真实项目里，「{ctx.kc_title}」通常作为「{depend_str}」的基础出现，"
                f"服务于「{goal_str}」这个更大的目标。\n\n"
                "落地时建议固定记录四件事：输入是什么、用了哪些关键参数、输出是什么、"
                "以及失败时的表现。把这四项记下来，结果才可复现，出问题时也才定位得到原因。"
            ),
        )
    )

    blocks.append(
        ExplanationBlock(
            type=BlockType.RECAP,
            title="总结",
            data={
                "points": [
                    f"用输入 → 关键变换 → 输出这条主线解释「{ctx.kc_title}」。",
                    "说清它成立的前提和失效的边界，而不只是记住结论。",
                    f"把它与前置 {prereq_str}、后续 {depend_str} 连成一条线。",
                    "动手走一遍完整例子，并用一个反例检验理解。",
                ]
            },
        )
    )

    blocks.append(
        ExplanationBlock(
            type=BlockType.HANDOFF,
            title="进入相关实践",
            content="读完这一节，可以进入相关实践，把刚才建立的模型用到一个小而完整的任务上。",
        )
    )
    return blocks
