from edu_agent.config.settings import get_settings
from edu_agent.core.exceptions import LLMConfigurationError


def get_llm(temperature: float = 0.3):
    """Create a LangChain ChatOpenAI instance from shared settings."""

    from langchain_openai import ChatOpenAI

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMConfigurationError(
            "OPENAI_API_KEY is not configured. Please set it in .env."
        )

    kwargs = {
        "api_key": settings.openai_api_key,
        "model": settings.openai_model,
        "temperature": temperature,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url

    return ChatOpenAI(**kwargs)
