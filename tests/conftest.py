"""全局测试配置：强制整测试套件离线（不触碰任何真实 LLM / search provider）。

为什么需要它：
- 多个测试直接调用 ``generate_plan()`` / ``/plan/generate`` / ``/api/chat``，
  这些路径内部会跑真实 ``run_study_plan_workflow`` 或 ``get_kb_llm``。
- 这些测试**本意**是“无 provider 时走确定性降级模板”，但过去只在少数文件里
  手动 ``monkeypatch.setenv(key, "")`` 清零，存在大量漏网（如
  ``test_plan_step_context.py``、``test_application.py``、``test_ownership_rag.py``
  中除 smoke 外的 ``generate_plan`` 调用）——只要开发机 ``.env`` 配了 provider，
  它们就会真实打模型、产生费用与不确定性。
- 这里用 autouse fixture 在每个测试前统一清空所有 provider key，使
  ``_resolve_main_settings`` 必然抛 ``LLMConfigurationError`` → production 代码
  立即走离线降级（workflow 降级模板 / chat ``_fallback_reply``），整库零真实网络。

注意：
- **不清 ``OPENAI_MODEL``**：保留默认 ``"deepseek-chat"``，否则
  ``test_settings_defaults_are_loadable``（断言 ``settings.openai_model`` 非空）
  会失败。仅 model 名不会启用 provider（启用需 api_key 或 base_url）。
- 这是纯测试改动：不修改任何 production 代码，符合 V1 Freeze 约束。
- 各测试文件里原有的 ``setenv(key, "")`` 清零逻辑保留（冗余但无害，且更显式）。
"""

import pytest

# 启用的判定来自 src/edu_agent/core/llm.py::_resolve_main_settings：
#   OPENAI_API_KEY / OPENAI_BASE_URL 优先；否则 XINGCHEN_* / OPENCODE_ZEN_*；
#   都空才抛 LLMConfigurationError。TAVILY 是联网搜索，同样需要离线。
_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "XINGCHEN_API_KEY",
    "XINGCHEN_BASE_URL",
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_ZEN_BASE_URL",
    "TAVILY_API_KEY",
)


@pytest.fixture(autouse=True)
def _offline_provider_config(monkeypatch):
    """每个测试前清空 provider 配置，强制 production 走离线降级（零真实网络）。"""
    from edu_agent.config.settings import get_settings

    for key in _PROVIDER_KEYS:
        monkeypatch.setenv(key, "")
    # get_settings 是 lru_cache：清空缓存让上面的空配置在测试内立即生效
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
