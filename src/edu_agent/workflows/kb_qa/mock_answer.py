"""演示模式回答生成器：未配置模型 API 时，用知识库原文提炼出模拟 AI 讲解。

输出格式与真实大模型回答一致（结论 + 分步讲解 + 引用标注），
并明确标注"演示模式"，保证合规与诚实。
"""

from __future__ import annotations

import re
from typing import List

from edu_agent.tools.course_kb import KbChunk

_SENTENCE_SPLIT_RE = re.compile(r"[\n。；;！!？?]")


def _first_sentence(text: str, min_len: int = 10, max_len: int = 80) -> str:
    """从块文本中提取第一个有信息量的句子，跳过代码块与标题行。"""
    parts = _SENTENCE_SPLIT_RE.split(text)
    for part in parts:
        candidate = part.strip()
        if not candidate or candidate.startswith("```") or candidate.startswith("#"):
            continue
        # 剥离列表符号后判断，保证"易错点"这类列表内容也能被提取
        candidate = re.sub(r"^[-*|]\s*", "", candidate).strip()
        if not candidate:
            continue
        candidate = re.sub(r"\s+", " ", candidate).strip().rstrip("：:，,；;")
        if min_len <= len(candidate) <= max_len:
            return candidate
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:max_len] + ("..." if len(compact) > max_len else "")


def build_mock_answer(question: str, hits: List[KbChunk]) -> str:
    """基于命中的知识块生成演示模式回答（不调用任何模型）。"""
    primary = hits[0]
    conclusion = _first_sentence(primary.text)
    lines = [
        f"**结论**：「{question}」这个问题，知识库《{primary.doc_title}》的"
        f"「{primary.heading_path}」里有直接说明：{conclusion} [1]",
        "",
        "**分步讲解**：",
    ]
    rest = hits[1:3]
    if rest:
        for index, chunk in enumerate(rest, start=2):
            sentence = _first_sentence(chunk.text)
            lines.append(f"{index}. 进一步看「{chunk.heading_path}」：{sentence} [{index}]")
    else:
        lines.append(f"知识库中「{primary.heading_path}」是相关内容最直接的出处，可展开上方引用查看原文。")
    lines.extend(
        [
            "",
            "> 当前为**演示模式**（未配置模型 API），以上内容由知识库原文提炼生成；"
            "配置 `XINGCHEN_API_KEY` 或 `OPENAI_API_KEY` 后，将切换为大模型生成的口语化讲解。",
            "",
            f"你可以继续追问，例如：想了解「{primary.heading_path}」的易错点，"
            "或让我出一道相关练习题。",
        ]
    )
    return "\n".join(lines)
