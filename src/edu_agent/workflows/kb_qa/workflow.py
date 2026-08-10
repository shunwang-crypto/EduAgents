"""对话问答工作流（kb_qa）：知识库问答 + 来源引用 + AI 标识 + 模糊澄清 + 失败降级。

Adaptive 集成：调用方（AdaptiveService）把 LearnerState 压缩成
learner_context + adaptive_instructions 注入 prompt，EduAgents 不维护第二套画像。
"""

from __future__ import annotations

import re
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate

from edu_agent.config.settings import get_settings
from edu_agent.core.agent_runner import normalize_markdown_output
from edu_agent.core.llm import get_kb_llm
from edu_agent.tools.course_kb import CourseKnowledgeBase, KbChunk
from edu_agent.workflows.kb_qa.mock_answer import build_mock_answer
from edu_agent.workflows.kb_qa.prompts import CLARIFY_GUIDANCE, KB_QA_PROMPT
from edu_agent.workflows.kb_qa.rules import is_vague, should_mock_from_settings
from edu_agent.workflows.kb_qa.schemas import KbAnswer, KbCitation
from edu_agent.workflows.study_plan.schemas import StudentInput

_CLARIFY_DIRECTIONS = ["概念理解", "代码实现", "易错点"]

_EMPTY_HINT = (
    "请先输入你想问的问题。如果不知道从哪里开始，可以围绕某个具体知识点提问，"
    "例如『二叉树的前序遍历怎么写』。"
)

_NOT_COVERED_HINT = "知识库暂未覆盖「{question}」的相关内容，建议先进入学情诊断，让系统评估你的薄弱点后再针对性学习。"


def _snippet(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _build_citations(hits: List[KbChunk]) -> List[KbCitation]:
    return [
        KbCitation(
            title=chunk.doc_title,
            location=chunk.heading_path,
            snippet=_snippet(chunk.text),
            content=chunk.text,
        )
        for chunk in hits
    ]


def _suggested_questions(hits: List[KbChunk]) -> List[str]:
    if not hits:
        return []
    first_location = hits[0].heading_path
    return [
        f"把「{first_location}」展开成完整讲解",
        f"「{first_location}」有什么易错点？",
        f"「{first_location}」和它的前置知识有什么关系？",
    ]


def _fallback_answer(question: str, hits: List[KbChunk], reason: Exception) -> KbAnswer:
    """模型平台不可用/超时/异常时，用本地知识库检索结果拼装回答，不中断。"""
    lines = [
        "当前模型服务暂时不可用，以下为知识库中直接检索到的相关内容，可先对照原文学习：",
        "",
    ]
    for index, chunk in enumerate(hits, start=1):
        lines.append(f"[{index}] {chunk.heading_path}")
        lines.append(f"（来自《{chunk.doc_title}》）")
        lines.append(_snippet(chunk.text, limit=220))
        lines.append("")
    lines.append(f"稍后重试即可恢复完整讲解。降级原因：{reason}")
    return KbAnswer(
        intent="fallback",
        answer_markdown="\n".join(lines),
        citations=_build_citations(hits),
        ai_generated=True,
        suggested_questions=_suggested_questions(hits),
    )


def _resolve_mock(mock: Optional[bool]) -> bool:
    """演示模式开关：显式传参 > 环境变量 KB_QA_MOCK > 自动（配了 base_url 即真实模式）。"""
    return should_mock_from_settings(get_settings(), mock)


def run_kb_qa_workflow(
    question: str,
    knowledge_base: Optional[CourseKnowledgeBase] = None,
    student_input: Optional[StudentInput] = None,
    mock: Optional[bool] = None,
    learner_context: str = "",
    adaptive_instructions: str = "",
) -> KbAnswer:
    """
    对话问答工作流入口。

    流程：空/模糊提问 → 澄清引导（不调 LLM）
         → 知识库检索 → 未命中 → 明确"未覆盖 + 建议学情诊断"（不调 LLM，不编造）
         → 命中 → 演示模式（未配 API key，知识库原文模拟讲解，标注演示）
               → 星辰/主模型生成口语化分步回答（附真实引用）
         → 模型失败/超时 → 自动降级为本地检索结果拼装（不中断、不报错）

    mock 参数：True=强制演示模式；False=强制真实模型；None=自动判断（默认）。
    learner_context / adaptive_instructions：AdaptiveService 产出的画像上下文
        （EduAgents 不维护第二套画像，只消费外部 LearnerState 的压缩视图）。
    """
    question = (question or "").strip()
    if not question:
        return KbAnswer(
            intent="clarify",
            answer_markdown=_EMPTY_HINT,
            citations=[],
            ai_generated=True,
            suggested_directions=_CLARIFY_DIRECTIONS,
        )

    if is_vague(question):
        topic_hint = student_input.topic if student_input else "当前主题"
        return KbAnswer(
            intent="clarify",
            answer_markdown=CLARIFY_GUIDANCE.format(topic_hint=topic_hint),
            citations=[],
            ai_generated=True,
            suggested_directions=list(_CLARIFY_DIRECTIONS),
        )

    kb = knowledge_base or CourseKnowledgeBase()
    if kb.is_empty:
        hint = _NOT_COVERED_HINT.format(question=question)
        return KbAnswer(
            intent="not_covered",
            answer_markdown=hint,
            citations=[],
            ai_generated=True,
            diagnosis_hint=hint,
        )

    hits = kb.search(question, top_k=4)
    if not hits:
        hint = _NOT_COVERED_HINT.format(question=question)
        return KbAnswer(
            intent="not_covered",
            answer_markdown=hint,
            citations=[],
            ai_generated=True,
            diagnosis_hint=hint,
        )

    references = "\n\n".join(
        f"[{index}] 《{chunk.doc_title}》 {chunk.heading_path}\n{chunk.text}"
        for index, chunk in enumerate(hits, start=1)
    )
    citations = _build_citations(hits)

    if _resolve_mock(mock):
        return KbAnswer(
            intent="kb_answered",
            answer_markdown=build_mock_answer(question, hits),
            citations=citations,
            ai_generated=True,
            mock=True,
            suggested_questions=_suggested_questions(hits),
        )

    try:
        prompt = ChatPromptTemplate.from_template(KB_QA_PROMPT)
        response = (prompt | get_kb_llm(temperature=0.3)).invoke(
            {
                "references": references,
                "question": question,
                "learner_context": learner_context or "（暂无学生画像上下文，按通用水平回答）",
                "adaptive_instructions": adaptive_instructions or "直接清晰讲解。",
            }
        )
        answer = normalize_markdown_output(response)
        if not answer.strip():
            raise ValueError("模型返回了空回答")
        return KbAnswer(
            intent="kb_answered",
            answer_markdown=answer,
            citations=citations,
            ai_generated=True,
            suggested_questions=_suggested_questions(hits),
        )
    except Exception as exc:  # noqa: BLE001 - 任何模型异常都走本地降级，不打断对话
        return _fallback_answer(question, hits, exc)


def _stream_path_record(answer: KbAnswer, callback) -> None:
    """可选回调：把本次路径的 KbAnswer 暴露给调用方（用于前端拿 meta/citations）。"""
    if callback is not None:
        callback(answer)


def stream_kb_qa_answer(
    question: str,
    knowledge_base: Optional[CourseKnowledgeBase] = None,
    student_input: Optional[StudentInput] = None,
    mock: Optional[bool] = None,
    on_path: Optional[object] = None,
    learner_context: str = "",
    adaptive_instructions: str = "",
):
    """
    GPT 式流式生成器：yield 文本片段。

    - 流式输出仅对真实模型路径生效（每 token 一段）
    - 其他路径（clarify / not_covered / mock / fallback）整段作为单 token 流出
    - `on_path` 可选回调，签名 on_path(KbAnswer)；在决定路径后、yield 文本前调用，
      供前端拿到 answer 的元信息（meta/citations/ai_generated 等）以补全历史记录。
    - `learner_context` / `adaptive_instructions`：AdaptiveService 产出的画像上下文。
    """
    question = (question or "").strip()
    if not question:
        ans = KbAnswer(
            intent="clarify",
            answer_markdown=_EMPTY_HINT,
            citations=[],
            ai_generated=True,
            suggested_directions=list(_CLARIFY_DIRECTIONS),
        )
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
        return

    if is_vague(question):
        topic_hint = student_input.topic if student_input else "当前主题"
        ans = KbAnswer(
            intent="clarify",
            answer_markdown=CLARIFY_GUIDANCE.format(topic_hint=topic_hint),
            citations=[],
            ai_generated=True,
            suggested_directions=list(_CLARIFY_DIRECTIONS),
        )
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
        return

    kb = knowledge_base or CourseKnowledgeBase()
    if kb.is_empty:
        hint = _NOT_COVERED_HINT.format(question=question)
        ans = KbAnswer(
            intent="not_covered",
            answer_markdown=hint,
            citations=[],
            ai_generated=True,
            diagnosis_hint=hint,
        )
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
        return

    hits = kb.search(question, top_k=4)
    if not hits:
        hint = _NOT_COVERED_HINT.format(question=question)
        ans = KbAnswer(
            intent="not_covered",
            answer_markdown=hint,
            citations=[],
            ai_generated=True,
            diagnosis_hint=hint,
        )
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
        return

    citations = _build_citations(hits)
    if _resolve_mock(mock):
        ans = KbAnswer(
            intent="kb_answered",
            answer_markdown=build_mock_answer(question, hits),
            citations=citations,
            ai_generated=True,
            mock=True,
            suggested_questions=_suggested_questions(hits),
        )
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
        return

    # 真实生成：逐 token 流式
    references = "\n\n".join(
        f"[{index}] 《{chunk.doc_title}》 {chunk.heading_path}\n{chunk.text}"
        for index, chunk in enumerate(hits, start=1)
    )
    placeholder = KbAnswer(
        intent="kb_answered",
        answer_markdown="",
        citations=citations,
        ai_generated=True,
        suggested_questions=_suggested_questions(hits),
    )
    _stream_path_record(placeholder, on_path)

    try:
        prompt = ChatPromptTemplate.from_template(KB_QA_PROMPT)
        for chunk in (prompt | get_kb_llm(temperature=0.3)).stream(
            {
                "references": references,
                "question": question,
                "learner_context": learner_context or "（暂无学生画像上下文，按通用水平回答）",
                "adaptive_instructions": adaptive_instructions or "直接清晰讲解。",
            }
        ):
            yield chunk
    except Exception as exc:  # noqa: BLE001 - 流式异常也走降级，不打断
        ans = _fallback_answer(question, hits, exc)
        _stream_path_record(ans, on_path)
        yield ans.answer_markdown
