from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"] = Field(description="消息角色")
    content: str = Field(description="消息内容")


class PlanChatAnswer(BaseModel):
    intent: str = Field(description="问题意图，例如 explanation / exercise / resource / adjustment")
    answer_markdown: str = Field(description="面向学生的 Markdown 回答")
    citations: List[str] = Field(description="本次回答实际使用的资源 URL")
    suggested_questions: List[str] = Field(description="建议继续追问的问题")
    plan_change_suggested: bool = Field(description="是否建议修改当前学习计划")
    plan_change_summary: Optional[str] = Field(default=None, description="建议的计划修改摘要")

