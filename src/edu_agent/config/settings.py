import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    """Application settings loaded from environment variables（范围收缩版）。"""

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-chat", alias="OPENAI_MODEL")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # Google Gemini API 的 OpenAI-compatible endpoint
    model_routing_enabled: bool = Field(default=False, alias="MODEL_ROUTING_ENABLED")
    google_openai_api_key: str = Field(default="", alias="GOOGLE_OPENAI_API_KEY")
    google_openai_base_url: Optional[str] = Field(default=None, alias="GOOGLE_OPENAI_BASE_URL")
    google_text_model: str = Field(default="", alias="GOOGLE_TEXT_MODEL")
    google_vision_model: str = Field(default="", alias="GOOGLE_VISION_MODEL")
    llm_request_timeout_seconds: float = Field(default=600.0, alias="LLM_REQUEST_TIMEOUT_SECONDS")

    # 星辰平台（OpenAI 兼容；保留原有独立配置）
    xingchen_api_key: str = Field(default="", alias="XINGCHEN_API_KEY")
    xingchen_base_url: Optional[str] = Field(default=None, alias="XINGCHEN_BASE_URL")
    xingchen_model: str = Field(default="", alias="XINGCHEN_MODEL")

    # 本地 Dynamic Learner Model（SQLite）
    learner_model_db_path: str = Field(default="", alias="LEARNER_MODEL_DB_PATH")
    learner_model_auto_update: bool = Field(default=True, alias="LEARNER_MODEL_AUTO_UPDATE")
    # 开发期默认用户（默认空=必须由 X-User-Id 头提供；开发 .env 显式配置）
    learner_model_user_id: str = Field(default="", alias="LEARNER_MODEL_USER_ID")
    # CORS：逗号分隔的允许 origin（开发默认本地 Vite）
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )


@lru_cache
def get_settings() -> Settings:
    auto_update_raw = os.getenv("LEARNER_MODEL_AUTO_UPDATE", "").strip().lower()
    auto_update = auto_update_raw not in {"0", "false", "no", "off"}
    return Settings(
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
        OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL") or None,
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "deepseek-chat"),
        TAVILY_API_KEY=os.getenv("TAVILY_API_KEY", ""),
        MODEL_ROUTING_ENABLED=os.getenv("MODEL_ROUTING_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"},
        GOOGLE_OPENAI_API_KEY=os.getenv("GOOGLE_OPENAI_API_KEY", "").strip(),
        GOOGLE_OPENAI_BASE_URL=os.getenv("GOOGLE_OPENAI_BASE_URL") or None,
        GOOGLE_TEXT_MODEL=os.getenv("GOOGLE_TEXT_MODEL", "").strip(),
        GOOGLE_VISION_MODEL=os.getenv("GOOGLE_VISION_MODEL", "").strip(),
        LLM_REQUEST_TIMEOUT_SECONDS=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "600")),
        XINGCHEN_API_KEY=os.getenv("XINGCHEN_API_KEY", ""),
        XINGCHEN_BASE_URL=os.getenv("XINGCHEN_BASE_URL") or None,
        XINGCHEN_MODEL=os.getenv("XINGCHEN_MODEL", ""),
        LEARNER_MODEL_DB_PATH=os.getenv("LEARNER_MODEL_DB_PATH", "").strip(),
        LEARNER_MODEL_AUTO_UPDATE=auto_update,
        LEARNER_MODEL_USER_ID=os.getenv("LEARNER_MODEL_USER_ID", "").strip(),
        CORS_ORIGINS=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").strip(),
    )
