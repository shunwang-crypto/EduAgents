from typing import List

from pydantic import BaseModel, Field


class TopicDetail(BaseModel):
    title: str = Field(description="知识点名称")
    learning_objective: str = Field(description="本次学习的可检查目标")
    explanation_markdown: str = Field(description="知识点核心讲解 Markdown")
    example_markdown: str = Field(description="直观示例、代码或计算过程 Markdown")
    common_mistakes: List[str] = Field(description="常见错误")
    completion_checks: List[str] = Field(description="完成检查标准（理解检查，非评分）")
    next_learning_suggestions: List[str] = Field(
        default_factory=list, description="下一步学习建议（关联知识、前置补充）"
    )
    suggested_questions: List[str] = Field(description="建议继续追问的问题")
    resource_urls: List[str] = Field(description="实际使用的参考资源 URL")
    adaptive_decision_summary: str = Field(
        default="", description="本次讲解依据的自适应决策摘要（可选）"
    )
