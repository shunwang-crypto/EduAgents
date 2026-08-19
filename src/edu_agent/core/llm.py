import re

from edu_agent.config.settings import get_settings
from edu_agent.core.exceptions import LLMConfigurationError

try:
    from langchain_openai import ChatOpenAI as _ChatOpenAI
except ImportError:  # pragma: no cover - 未安装时仍允许模块导入（语法检查/沙箱）
    _ChatOpenAI = None

try:
    from langchain_core.runnables import Runnable
except ImportError:  # pragma: no cover - 同上
    Runnable = object  # type: ignore[assignment,misc]


def _parse_model_list(model_str) -> list:
    """把模型配置解析成列表，支持逗号 / 竖线 / 空白分隔，按顺序作为 fallback 链。"""
    if not model_str:
        return []
    parts = [part.strip() for part in re.split(r"[,|]", str(model_str)) if part.strip()]
    return parts


class FallbackChatOpenAI(Runnable):
    """同一 base_url 下的多模型 fallback 链。

    主模型被限流（429）/失败/超时时自动切换到下一个模型，逐个尝试，
    全部失败才抛出最后一个异常。对调用方完全透明（仍可 prompt | llm）。

    为什么不继承 ChatOpenAI：pydantic V2 的 BaseModel 在 ``model_copy`` /
    ``__deepcopy__`` / 内部重建路径上会丢失 ``__init__`` 后设的私有属性
    （如之前的 ``_clients``、``_models``），导致 langchain 内部访问这些字段
    时 AttributeError。改为组合 + Runnable 协议，绕开 pydantic 校验。
    """

    def __init__(
        self,
        *,
        models,
        api_key: str,
        base_url,
        temperature: float,
        timeout: float = 60.0,
        **kwargs,
    ):
        models = [model for model in models if model]
        if not models:
            raise LLMConfigurationError(
                "模型列表为空：请配置 OPENAI_MODEL（可逗号分隔多个，如 "
                "nemotron-3-ultra-free,laguna-s-2.1-free）。"
            )
        self._models = models
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self._timeout = timeout
        self._extra_kwargs = dict(kwargs)

    def _client_for(self, model):
        """每次现构造 ChatOpenAI（构造开销极小，避免缓存私有属性被 pydantic 序列化丢失）。

        对 OpenCode Zen（opencode.ai）额外带 x-opencode-client: desktop 头，
        否则会被 Cloudflare 拦截（error 1010）。
        """
        headers = dict(self._extra_kwargs.get("default_headers", {}) or {})
        if "opencode.ai" in (self._base_url or ""):
            headers.setdefault("x-opencode-client", "desktop")
        return _ChatOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            model=model,
            temperature=self._temperature,
            timeout=self._timeout,
            default_headers=headers,
            **self._extra_kwargs,
        )

    def invoke(self, input, config=None, **kwargs):
        last_error = None
        for model in self._models:
            try:
                return self._client_for(model).invoke(input, config=config, **kwargs)
            except Exception as exc:  # noqa: BLE001 - 任一模型失败即切换下一个
                last_error = exc
        raise last_error

    def stream(self, input, config=None, **kwargs):
        """逐 token 流式；请求阶段失败（如 429 限额）自动切换下一个模型重新开始。"""
        last_error = None
        for model in self._models:
            try:
                yield from self._client_for(model).stream(input, config=config, **kwargs)
                return
            except Exception as exc:  # noqa: BLE001 - 请求阶段失败即切换
                last_error = exc
        raise last_error


def _resolve_main_settings():
    """
    主模型配置解析：
    1. OPENAI_* 优先；
    2. 未配置 OPENAI 时回落星辰平台（XINGCHEN_* / OPENCODE_ZEN_* 别名）；
    3. key 可为空（OpenCode Zen 免费模型不需要 key，配 base_url 即可，
       此时 api_key 传空字符串，请求只带空 Bearer 头）；
    4. base_url 与 key 都未配置才报错。
    """
    settings = get_settings()
    if settings.openai_api_key or settings.openai_base_url:
        return settings.openai_api_key or "", settings.openai_base_url, settings.openai_model
    if settings.xingchen_api_key or settings.xingchen_base_url:
        return (
            settings.xingchen_api_key or "",
            settings.xingchen_base_url,
            settings.xingchen_model or settings.openai_model,
        )
    raise LLMConfigurationError(
        "未配置任何模型：请设置 OPENAI_API_KEY / OPENAI_BASE_URL，或星辰平台 "
        "XINGCHEN_API_KEY / XINGCHEN_BASE_URL（含 OPENCODE_ZEN_* 别名，见 .env.example）。"
    )


def get_llm(temperature: float = 0.3, **kwargs):
    """创建带多模型 fallback 的 ChatOpenAI：OPENAI_* 优先，未配置时回落星辰平台。"""

    # OFFLINE 测试模式：跳过真实 LLM，立即触发调用方 fallback，避免无 API 环境等待超时。
    import os as _os
    if _os.environ.get("EDU_OFFLINE", "").strip() in ("1", "true", "True"):
        raise RuntimeError("EDU_OFFLINE: skipping LLM")

    api_key, base_url, model_str = _resolve_main_settings()
    return FallbackChatOpenAI(
        models=_parse_model_list(model_str),
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        **kwargs,
    )


def get_kb_llm(temperature: float = 0.3, **kwargs):
    """
    对话问答工作流专用实例：优先使用星辰平台（XINGCHEN_* / OPENCODE_ZEN_*）；
    星辰 key 可留空（OpenCode Zen 免费模型无需 key）；未配置星辰时回落 OPENAI_*。
    kwargs 可透传 request_timeout 等参数。
    """

    settings = get_settings()
    if settings.xingchen_api_key or settings.xingchen_base_url:
        model_str = settings.xingchen_model or settings.openai_model
        base_url = settings.xingchen_base_url or settings.openai_base_url
        return FallbackChatOpenAI(
            models=_parse_model_list(model_str),
            api_key=settings.xingchen_api_key or "",
            base_url=base_url,
            temperature=temperature,
            **kwargs,
        )
    return get_llm(temperature=temperature, **kwargs)
