from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class KbCitation(BaseModel):
    """回答中一条可展示的来源引用。"""

    title: str = Field(description="来源文档标题")
    location: str = Field(description="来源定位，例如章节路径『第3章 二叉树 > 3.2 遍历』")
    snippet: str = Field(description="命中片段摘要（短）")
    content: str = Field(
        default="",
        description="来源文档块的完整内容（用于点击展开后查看具体详情）",
    )


class KbAnswer(BaseModel):
    """
    对话问答工作流的回答。

    intent 取值：
    - clarify     ：提问过于笼统，需要学生先选择具体方向
    - kb_answered ：基于知识库内容正常回答（附引用）
    - not_covered ：知识库未覆盖，明确引导进入学情诊断，不编造
    - fallback    ：模型平台不可用/超时/异常，回落本地知识库检索结果拼装
    """

    intent: Literal["clarify", "kb_answered", "not_covered", "fallback"] = Field(
        description="回答意图"
    )
    answer_markdown: str = Field(description="面向学生的 Markdown 回答")
    citations: List[KbCitation] = Field(
        default_factory=list, description="本次回答实际使用的来源引用"
    )
    ai_generated: bool = Field(default=True, description="是否为 AI 生成内容（合规标识）")
    mock: bool = Field(
        default=False,
        description="是否为演示模式回答（未配置模型 API 时用知识库原文模拟生成）",
    )
    suggested_directions: List[str] = Field(
        default_factory=list,
        description="澄清引导方向，例如『概念 / 代码实现 / 易错点』",
    )
    suggested_questions: List[str] = Field(
        default_factory=list, description="建议继续追问的问题"
    )
    diagnosis_hint: Optional[str] = Field(
        default=None, description="知识库未覆盖时给出的下一步建议文案"
    )
