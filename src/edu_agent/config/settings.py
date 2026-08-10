import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-chat", alias="OPENAI_MODEL")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # 星辰平台（对话问答专用，OpenAI 兼容）。未配置 XINGCHEN_API_KEY 时
    # 对话问答回落使用 OPENAI_* 配置。
    # 兼容别名：OPENCODE_ZEN_*（星辰平台另一种变量命名）等价于 XINGCHEN_*。
    xingchen_api_key: str = Field(default="", alias="XINGCHEN_API_KEY")
    xingchen_base_url: Optional[str] = Field(default=None, alias="XINGCHEN_BASE_URL")
    xingchen_model: str = Field(default="", alias="XINGCHEN_MODEL")

    # 对话问答演示模式：true=强制演示（不调模型）；false=强制真实模型；
    # 留空/不配置=自动（未配置任何模型 API key 时自动进入演示模式）。
    kb_qa_mock: Optional[bool] = Field(default=None, alias="KB_QA_MOCK")

    # 学习者画像（LearnerState）外部服务
    learner_state_provider: str = Field(default="auto", alias="LEARNER_STATE_PROVIDER")
    learner_state_base_url: str = Field(default="", alias="LEARNER_STATE_BASE_URL")
    learner_state_api_key: str = Field(default="", alias="LEARNER_STATE_API_KEY")
    learner_state_timeout_seconds: float = Field(default=8.0, alias="LEARNER_STATE_TIMEOUT_SECONDS")
    learner_state_cache_ttl: int = Field(default=300, alias="LEARNER_STATE_CACHE_TTL")
    learner_state_course_id: str = Field(default="JAVA-OOP", alias="LEARNER_STATE_COURSE_ID")
    learner_state_user_id: str = Field(default="STU-001", alias="LEARNER_STATE_USER_ID")

    # 学习事件回传
    learning_event_delivery_enabled: bool = Field(default=False, alias="LEARNING_EVENT_DELIVERY_ENABLED")
    learning_event_delivery_url: str = Field(default="", alias="LEARNING_EVENT_DELIVERY_URL")


@lru_cache
def get_settings() -> Settings:
    mock_raw = os.getenv("KB_QA_MOCK", "").strip().lower()
    mock_value: Optional[bool] = None
    if mock_raw in {"1", "true", "yes", "on", "演示"}:
        mock_value = True
    elif mock_raw in {"0", "false", "no", "off"}:
        mock_value = False

    event_enabled_raw = os.getenv("LEARNING_EVENT_DELIVERY_ENABLED", "").strip().lower()
    event_enabled = event_enabled_raw in {"1", "true", "yes", "on"}

    return Settings(
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
        OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL") or None,
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "deepseek-chat"),
        TAVILY_API_KEY=os.getenv("TAVILY_API_KEY", ""),
        XINGCHEN_API_KEY=os.getenv("XINGCHEN_API_KEY")
        or os.getenv("OPENCODE_ZEN_API_KEY", ""),
        XINGCHEN_BASE_URL=os.getenv("XINGCHEN_BASE_URL")
        or os.getenv("OPENCODE_ZEN_BASE_URL")
        or None,
        XINGCHEN_MODEL=os.getenv("XINGCHEN_MODEL") or os.getenv("OPENCODE_ZEN_MODEL", ""),
        KB_QA_MOCK=mock_value,
        LEARNER_STATE_PROVIDER=os.getenv("LEARNER_STATE_PROVIDER", "auto").strip() or "auto",
        LEARNER_STATE_BASE_URL=os.getenv("LEARNER_STATE_BASE_URL", "").strip(),
        LEARNER_STATE_API_KEY=os.getenv("LEARNER_STATE_API_KEY", "").strip(),
        LEARNER_STATE_TIMEOUT_SECONDS=float(
            os.getenv("LEARNER_STATE_TIMEOUT_SECONDS", "8.0") or 8.0
        ),
        LEARNER_STATE_CACHE_TTL=int(os.getenv("LEARNER_STATE_CACHE_TTL", "300") or 300),
        LEARNER_STATE_COURSE_ID=os.getenv("LEARNER_STATE_COURSE_ID", "JAVA-OOP").strip()
        or "JAVA-OOP",
        LEARNER_STATE_USER_ID=os.getenv("LEARNER_STATE_USER_ID", "STU-001").strip()
        or "STU-001",
        LEARNING_EVENT_DELIVERY_ENABLED=event_enabled,
        LEARNING_EVENT_DELIVERY_URL=os.getenv("LEARNING_EVENT_DELIVERY_URL", "").strip(),
    )
