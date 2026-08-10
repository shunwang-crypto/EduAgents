import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.core import llm as llm_module  # noqa: E402


# ---------------------------------------------------------------------------
# 模型列表解析
# ---------------------------------------------------------------------------


def test_parse_model_list_splits_by_commas_and_pipes():
    assert llm_module._parse_model_list("a,b, c") == ["a", "b", "c"]
    assert llm_module._parse_model_list("a|b") == ["a", "b"]
    assert llm_module._parse_model_list("  a  ,  b  ,") == ["a", "b"]


def test_parse_model_list_handles_empty():
    assert llm_module._parse_model_list("") == []
    assert llm_module._parse_model_list(None) == []
    assert llm_module._parse_model_list(" , , ") == []


# ---------------------------------------------------------------------------
# Fallback 链：模拟 ChatOpenAI，第一个模型失败时自动切换下一个
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self, *, api_key, base_url, model, temperature, **kwargs):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def invoke(self, input, config=None, **kwargs):
        if self.model == "fail-model":
            raise RuntimeError("429 rate limit")
        return f"ok-{self.model}"

    def stream(self, input, config=None, **kwargs):
        if self.model == "fail-model":
            raise RuntimeError("429 rate limit")
        yield f"token-{self.model}"


@pytest.fixture
def patch_chat_openai(monkeypatch):
    monkeypatch.setattr(llm_module, "_ChatOpenAI", FakeClient)


def _build(models, **kwargs):
    return llm_module.FallbackChatOpenAI(
        models=models,
        api_key="",
        base_url="https://opencode.ai/zen/v1",
        temperature=0.3,
        **kwargs,
    )


def test_fallback_invoke_switches_to_next_model(patch_chat_openai):
    llm = _build(["fail-model", "good-model"])
    assert llm.invoke({"x": 1}) == "ok-good-model"


def test_fallback_invoke_uses_first_model_when_ok(patch_chat_openai):
    llm = _build(["good-model", "other-model"])
    assert llm.invoke({"x": 1}) == "ok-good-model"


def test_fallback_invoke_raises_when_all_models_fail(patch_chat_openai):
    llm = _build(["fail-model", "fail-model"])
    with pytest.raises(RuntimeError, match="429"):
        llm.invoke({"x": 1})


def test_fallback_stream_switches_on_request_failure(patch_chat_openai):
    llm = _build(["fail-model", "good-model"])
    assert list(llm.stream({"x": 1})) == ["token-good-model"]


def test_fallback_stream_uses_first_model_when_ok(patch_chat_openai):
    llm = _build(["good-model", "other-model"])
    assert list(llm.stream({"x": 1})) == ["token-good-model"]


def test_empty_model_list_raises(patch_chat_openai):
    with pytest.raises(llm_module.LLMConfigurationError):
        _build([])
