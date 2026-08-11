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

    # 星辰平台（OpenAI 兼容），兼容别名 OPENCODE_ZEN_*
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
        XINGCHEN_API_KEY=os.getenv("XINGCHEN_API_KEY")
        or os.getenv("OPENCODE_ZEN_API_KEY", ""),
        XINGCHEN_BASE_URL=os.getenv("XINGCHEN_BASE_URL")
        or os.getenv("OPENCODE_ZEN_BASE_URL")
        or None,
        XINGCHEN_MODEL=os.getenv("XINGCHEN_MODEL") or os.getenv("OPENCODE_ZEN_MODEL", ""),
        LEARNER_MODEL_DB_PATH=os.getenv("LEARNER_MODEL_DB_PATH", "").strip(),
        LEARNER_MODEL_AUTO_UPDATE=auto_update,
        LEARNER_MODEL_USER_ID=os.getenv("LEARNER_MODEL_USER_ID", "").strip(),
        CORS_ORIGINS=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").strip(),
    )
