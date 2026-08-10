"""
最小本地课程知识库（Course Knowledge Base）。

职责：
- 把 Markdown 教材文本按标题层级切分成带定位的块（doc_title + heading_path）。
- 用纯 Python 关键词检索（无第三方依赖：英文 token + 中文 2-gram）返回命中的块。
- 供对话问答工作流（kb_qa）作为"知识库依据"使用；后续可替换为向量检索实现，
  接口保持不变（search / chunks）。

设计约束：
- 不引入 jieba / numpy / 向量库，保证原型在任何 Python 3.10+ 环境开箱即用。
- 检索分数只用于排序与"是否命中"判断，不进入任何掌握度计算。
"""

from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

from edu_agent.tools.github_importer import import_github_repo


class KbChunk(BaseModel):
    """知识库中的一个可引用块。"""

    doc_title: str = Field(description="来源文档标题")
    heading_path: str = Field(description="标题定位路径，例如『第3章 二叉树 > 3.2 遍历』")
    text: str = Field(description="块正文")
    score: float = Field(default=0.0, description="与查询的相关性分数")


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_+#.]+")
_HANZI_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOPWORDS = {
    "这个", "那个", "什么", "怎么", "如何", "为什么", "可以", "一个", "一下",
    "我们", "你们", "他们", "进行", "使用", "需要", "应该", "没有", "就是",
    "请问", "帮忙", "看看", "问题", "回答", "知道", "意思", "哪里", "哪些",
    "了解", "学习", "讲解", "介绍", "是否", "能否", "如果", "然后", "并且",
    # 中文 2-gram 中常见的高频虚词组合（"是什么/怎么/为什么"的前两字）
    "是什", "怎实", "为什", "什", "么",
}


def _tokenize(text: str) -> List[str]:
    """英文小写 token + 中文 2-gram，去停用词。"""
    text = text.lower()
    tokens: List[str] = []
    for match in _ASCII_TOKEN_RE.findall(text):
        if len(match) >= 2:
            tokens.append(match)
    for hanzi in _HANZI_RE.findall(text):
        if len(hanzi) == 1:
            tokens.append(hanzi)
        else:
            tokens.extend(hanzi[index : index + 2] for index in range(len(hanzi) - 1))
    return [token for token in tokens if token not in _STOPWORDS]


def _split_markdown_blocks(name: str, text: str) -> List[KbChunk]:
    """按 Markdown 标题层级把文本切成带 heading_path 的块。"""
    blocks: List[KbChunk] = []
    heading_stack: List[tuple[int, str]] = []
    current_lines: List[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body and heading_stack:
            blocks.append(
                KbChunk(
                    doc_title=name,
                    heading_path=" > ".join(title for _, title in heading_stack),
                    text=body,
                )
            )
        current_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            # 栈里记录真实标题层级：新标题到来时，弹出所有层级 >= 它的祖先。
            # 用真实 level 而非栈长度比较，保证同级章节（如两个 h2）能正确互斥，
            # 文档从 h2/h3 开始（无 h1 顶层）时也不残留错误前缀。
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        elif line.strip():
            current_lines.append(line)
    flush()

    # 没有任何标题时，把全文作为单块，用文档名作为定位
    if not blocks and text.strip():
        blocks.append(KbChunk(doc_title=name, heading_path=name, text=text.strip()))
    return blocks


class CourseKnowledgeBase:
    """内存中的最小课程知识库。"""

    def __init__(self, sources: dict[str, str] | None = None) -> None:
        self._chunks: List[KbChunk] = []
        if sources:
            for name, text in sources.items():
                self.load_markdown(name, text)

    def load_markdown(self, name: str, text: str) -> int:
        """加载一份 Markdown 教材，返回新增块数。"""
        blocks = _split_markdown_blocks(name, text)
        self._chunks.extend(blocks)
        return len(blocks)

    @classmethod
    def from_chunks(cls, chunks: List["KbChunk"]) -> "CourseKnowledgeBase":
        """用已存在的块列表重建一个知识库实例（用于持久化加载）。"""
        obj = cls()
        obj._chunks = list(chunks)
        return obj

    def load_github_repo(self, url: str, **kwargs) -> int:
        """从 GitHub 仓库导入文档并建立索引，返回新增块数。

        kwargs 透传给 github_importer.import_github_repo（max_files / max_bytes / timeout）。
        """
        docs = import_github_repo(url, **kwargs)
        total_blocks = 0
        for name, text in docs.items():
            total_blocks += self.load_markdown(name, text)
        return total_blocks

    @property
    def chunks(self) -> List[KbChunk]:
        return list(self._chunks)

    @property
    def is_empty(self) -> bool:
        return not self._chunks

    def search(self, query: str, top_k: int = 4, min_hits: int = 2) -> List[KbChunk]:
        """
        关键词检索：命中当前小节标题权重 3，命中正文权重 1；
        父章节标题（如"第 4 章 知识库建设"）不参与计分，避免整章被抬高分；
        命中数低于 min_hits 视为未命中（返回空列表，用于"知识库未覆盖"判定）。
        """
        query_tokens = _tokenize(query or "")
        if not query_tokens or not self._chunks:
            return []

        scored: List[tuple[float, KbChunk]] = []
        for chunk in self._chunks:
            # 只取 heading_path 的最后一段作为"小节标题"参与加权
            title_text = chunk.heading_path.split(" > ")[-1].lower()
            body_text = chunk.text.lower()
            hits = 0
            for token in query_tokens:
                if token in title_text:
                    hits += 2
                elif token in body_text:
                    hits += 1
            if hits >= min_hits:
                scored.append((float(hits), chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]
