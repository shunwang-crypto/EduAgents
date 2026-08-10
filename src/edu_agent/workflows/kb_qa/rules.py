"""对话问答工作流的纯规则判定（无外部依赖，可单测）。"""

from __future__ import annotations

import re

from edu_agent.tools.course_kb import _ASCII_TOKEN_RE

# 口语功能字：出现时不提供"具体内容"信号，用于判定提问是否过于笼统。
_FUNCTION_CHARS = frozenset(
    "这那怎么什么哪谁啥咋为何的了是呢啊吧呀哦嗯我你他她它们个种些下一就也都很好"
    "帮看看写弄搞整做要想要能会去给让找用"
)
_ASCII_STOP = {
    "how", "what", "why", "when", "where", "which", "who", "this", "that",
    "it", "can", "do", "does", "is", "are", "the", "to", "for", "of", "and",
}

_PUNCTUATION_RE = re.compile(r"[\s，。？！、；：,.?!;:()（）“”\"'']+", re.UNICODE)

# 整句即口语疑问的短句白名单（直接判定为笼统提问）。
_VAGUE_PHRASES = {
    "咋回事", "怎么回事", "咋了", "咋啦", "怎么了", "为什么", "为啥", "凭啥",
    "如何", "怎么办", "怎么弄", "怎么做", "如何做", "如何办", "是什么", "干嘛",
    "啥意思", "什么意思", "什么", "干啥", "怎么", "为啥呢", "为什么呀", "怎样",
}


def has_content_signal(cleaned: str) -> bool:
    """判定文本中是否包含具体内容信号（汉字内容字或英文内容词）。"""
    hanzi_count = sum(
        1 for ch in cleaned if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNCTION_CHARS
    )
    if hanzi_count >= 2:
        return True
    # 大小写不敏感：BKT、LLM 这类大写缩写也要算内容信号
    ascii_tokens = [t.lower() for t in _ASCII_TOKEN_RE.findall(cleaned.lower())]
    return any(len(t) >= 3 and t not in _ASCII_STOP for t in ascii_tokens)


def is_vague(question: str) -> bool:
    """规则判定提问是否过于笼统（无需调 LLM）。"""
    cleaned = _PUNCTUATION_RE.sub("", question or "")
    if not cleaned:
        return True
    if len(cleaned) <= 2:
        return True
    if cleaned in _VAGUE_PHRASES:
        return True
    return not has_content_signal(cleaned)


def should_mock_from_settings(settings, explicit_mock=None) -> bool:
    """
    演示模式开关解析：显式传参 > 环境变量 KB_QA_MOCK > 自动。

    自动规则：只要配置了任一模型 base_url（OpenCode Zen 免费模型不需要 key），
    就走真实模型；什么都没配才进入演示模式。
    """
    if explicit_mock is not None:
        return bool(explicit_mock)
    if settings.kb_qa_mock is not None:
        return bool(settings.kb_qa_mock)
    return not bool(
        settings.xingchen_api_key
        or settings.xingchen_base_url
        or settings.openai_api_key
        or settings.openai_base_url
    )
