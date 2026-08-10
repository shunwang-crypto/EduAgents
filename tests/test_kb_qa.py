import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.tools.course_kb import CourseKnowledgeBase  # noqa: E402
from edu_agent.workflows.kb_qa import workflow as kb_qa_module  # noqa: E402
from edu_agent.workflows.kb_qa.rules import is_vague  # noqa: E402
from edu_agent.workflows.kb_qa.workflow import run_kb_qa_workflow  # noqa: E402

# 测试用迷你知识库（内置示例数据已删除，测试显式传入知识库）
MINI_KB_SOURCES = {
    "二叉树讲义.md": """## 第 1 章 二叉树基础

二叉树是每个节点最多有两个子节点的树结构。

### 1.1 为什么需要二叉树

二叉树用于高效查找、排序与表达式求值。

## 第 2 章 二叉树的遍历

### 2.1 遍历方式

前序：根左右；中序：左根右；后序：左右根；层序：逐层。

### 2.2 代码实现

前序遍历代码：先访问根，再递归左子树，最后递归右子树。

### 2.3 层序遍历

层序遍历使用队列逐层访问。
""",
    "教育智能体实现指南.md": """## 第 5 章 学情诊断

### 5.1 BKT 是什么

BKT（贝叶斯知识追踪）根据答题序列估计知识点掌握概率。

## 第 7 章 模型网关与成本

### 7.1 成本怎么控制

通过模型分级、缓存与降级控制调用成本。
""",
}


def _make_kb() -> CourseKnowledgeBase:
    return CourseKnowledgeBase(dict(MINI_KB_SOURCES))


def _patch_llm_chain(monkeypatch, answer=None, error=None):
    """替换 ChatPromptTemplate 与 get_kb_llm，不触发真实模型调用。"""

    class FakeChain:
        def __init__(self):
            self._answer = answer
            self._error = error

        def invoke(self, values):
            if self._error is not None:
                raise self._error
            return self._answer

    class FakePrompt:
        def __or__(self, llm):
            return FakeChain()

    class FakePromptTemplate:
        @staticmethod
        def from_template(text):
            return FakePrompt()

    monkeypatch.setattr(kb_qa_module, "ChatPromptTemplate", FakePromptTemplate)
    monkeypatch.setattr(kb_qa_module, "get_kb_llm", lambda *args, **kwargs: object())


DEFAULT_ANSWER = (
    "**结论**：前序遍历按『根左右』顺序访问节点。\n\n"
    "1. 先访问根节点 [1]\n2. 再遍历左子树 [1]\n3. 最后遍历右子树 [1]"
)


# ---------------------------------------------------------------------------
# 知识库分块与检索
# ---------------------------------------------------------------------------


def test_kb_splits_into_located_blocks():
    kb = _make_kb()
    assert kb.is_empty is False
    paths = [chunk.heading_path for chunk in kb.chunks]
    assert "第 2 章 二叉树的遍历 > 2.2 代码实现" in paths
    assert len(kb.chunks) >= 6


def test_kb_search_finds_matching_block():
    kb = _make_kb()
    hits = kb.search("二叉树的前序遍历怎么写", top_k=3)
    assert hits
    assert any("前序" in hit.heading_path or "遍历" in hit.heading_path for hit in hits)


def test_kb_search_miss_returns_empty():
    kb = _make_kb()
    assert kb.search("量子纠缠的贝尔不等式", top_k=3) == []


# ---------------------------------------------------------------------------
# 对话问答工作流
# ---------------------------------------------------------------------------


def test_is_vague_rule():
    vague_cases = ["这个怎么弄", "帮我看看", "咋回事", "啥", "那是什么", "干嘛", "怎么写", "怎么回事"]
    clear_cases = [
        "二叉树的前序遍历怎么写",
        "中序遍历的代码",
        "层序遍历和深度优先的区别",
        "为什么需要二叉树",
        "python dict get",
    ]
    for question in vague_cases:
        assert is_vague(question), f"应为模糊提问: {question}"
    for question in clear_cases:
        assert not is_vague(question), f"不应判定为模糊: {question}"


def test_vague_question_returns_clarify_without_llm(monkeypatch):
    _patch_llm_chain(monkeypatch, error=AssertionError("模糊提问不应调用模型"))
    answer = run_kb_qa_workflow("这个怎么弄")
    assert answer.intent == "clarify"
    assert answer.ai_generated is True
    assert answer.mock is False
    assert answer.citations == []
    assert answer.suggested_directions == ["概念理解", "代码实现", "易错点"]


def test_empty_question_returns_clarify(monkeypatch):
    _patch_llm_chain(monkeypatch, error=AssertionError("空提问不应调用模型"))
    answer = run_kb_qa_workflow("   ")
    assert answer.intent == "clarify"
    assert answer.ai_generated is True


def test_not_covered_returns_guidance_without_llm(monkeypatch):
    _patch_llm_chain(monkeypatch, error=AssertionError("未覆盖提问不应调用模型"))
    answer = run_kb_qa_workflow("量子纠缠的贝尔不等式怎么证明")
    assert answer.intent == "not_covered"
    assert answer.ai_generated is True
    assert "知识库暂未覆盖" in answer.answer_markdown
    assert "学情诊断" in answer.answer_markdown
    assert answer.citations == []
    assert answer.diagnosis_hint


def test_hit_returns_llm_answer_with_real_citations(monkeypatch):
    _patch_llm_chain(monkeypatch, answer=DEFAULT_ANSWER)
    answer = run_kb_qa_workflow(
        "二叉树的前序遍历怎么写",
        knowledge_base=_make_kb(),
        mock=False,
    )
    assert answer.intent == "kb_answered"
    assert answer.ai_generated is True
    assert answer.mock is False
    assert answer.citations
    for citation in answer.citations:
        assert citation.title == "二叉树讲义.md"
        assert citation.location
        assert citation.snippet
        assert citation.content  # 完整文档内容，供点击引用展开查看
    assert answer.suggested_questions


def test_llm_failure_falls_back_to_local(monkeypatch):
    _patch_llm_chain(monkeypatch, error=RuntimeError("星辰平台超时"))
    answer = run_kb_qa_workflow(
        "中序遍历的代码怎么写",
        knowledge_base=_make_kb(),
        mock=False,
    )
    assert answer.intent == "fallback"
    assert answer.ai_generated is True
    assert answer.citations
    assert "知识库" in answer.answer_markdown
    assert "降级" in answer.answer_markdown


def test_empty_llm_answer_falls_back(monkeypatch):
    _patch_llm_chain(monkeypatch, answer="   \n  ")
    answer = run_kb_qa_workflow(
        "层序遍历怎么写",
        knowledge_base=_make_kb(),
        mock=False,
    )
    assert answer.intent == "fallback"
    assert answer.citations


# ---------------------------------------------------------------------------
# 演示模式（mock）
# ---------------------------------------------------------------------------


def test_mock_mode_returns_demo_answer_without_llm(monkeypatch):
    _patch_llm_chain(monkeypatch, error=AssertionError("演示模式不应调用模型"))
    answer = run_kb_qa_workflow(
        "二叉树的前序遍历怎么写",
        knowledge_base=_make_kb(),
        mock=True,
    )
    assert answer.intent == "kb_answered"
    assert answer.mock is True
    assert answer.ai_generated is True
    assert answer.citations
    assert "演示模式" in answer.answer_markdown
    assert "分步讲解" in answer.answer_markdown


def test_mock_auto_enabled_when_no_api_key(monkeypatch):
    import types

    _patch_llm_chain(monkeypatch, error=AssertionError("无 key 无 base_url 时应走演示模式"))
    monkeypatch.setattr(
        kb_qa_module,
        "get_settings",
        lambda: types.SimpleNamespace(
            kb_qa_mock=None,
            xingchen_api_key="",
            xingchen_base_url="",
            openai_api_key="",
            openai_base_url="",
        ),
    )
    answer = run_kb_qa_workflow(
        "前序遍历的代码",
        knowledge_base=_make_kb(),
    )
    assert answer.intent == "kb_answered"
    assert answer.mock is True


def test_mock_auto_disabled_when_api_key_present(monkeypatch):
    import types

    _patch_llm_chain(monkeypatch, answer=DEFAULT_ANSWER)
    monkeypatch.setattr(
        kb_qa_module,
        "get_settings",
        lambda: types.SimpleNamespace(
            kb_qa_mock=None,
            xingchen_api_key="sk-xingchen-demo",
            xingchen_base_url="https://zen.example.com/v1",
            openai_api_key="",
            openai_base_url="",
        ),
    )
    answer = run_kb_qa_workflow(
        "前序遍历的代码",
        knowledge_base=_make_kb(),
    )
    assert answer.intent == "kb_answered"
    assert answer.mock is False


def test_mock_auto_disabled_with_base_url_only_no_key(monkeypatch):
    """OpenCode Zen 免费模型：只配 base_url、不配 key 也应走真实模型。"""
    import types

    _patch_llm_chain(monkeypatch, answer=DEFAULT_ANSWER)
    monkeypatch.setattr(
        kb_qa_module,
        "get_settings",
        lambda: types.SimpleNamespace(
            kb_qa_mock=None,
            xingchen_api_key="",
            xingchen_base_url="https://opencode.ai/zen/v1",
            openai_api_key="",
            openai_base_url="",
        ),
    )
    answer = run_kb_qa_workflow(
        "前序遍历的代码",
        knowledge_base=_make_kb(),
    )
    assert answer.intent == "kb_answered"
    assert answer.mock is False


def test_settings_supports_opencode_zen_alias(monkeypatch):
    from edu_agent.config.settings import get_settings

    monkeypatch.delenv("XINGCHEN_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "sk-zen-demo")
    monkeypatch.setenv("OPENCODE_ZEN_BASE_URL", "https://zen.example.com/v1")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.xingchen_api_key == "sk-zen-demo"
        assert settings.xingchen_base_url == "https://zen.example.com/v1"
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GPT 式流式输出（stream_kb_qa_answer）
# ---------------------------------------------------------------------------


def test_stream_emits_clarify_intent_and_invokes_callback(monkeypatch):
    from edu_agent.workflows.kb_qa import workflow as kb_qa_module

    _patch_llm_chain(monkeypatch, error=AssertionError("澄清不应调模型"))
    captured: dict = {}

    chunks = list(
        kb_qa_module.stream_kb_qa_answer(
            "这个怎么弄", on_path=lambda ans: captured.setdefault("answer", ans)
        )
    )
    assert chunks and isinstance(chunks[0], str)
    assert "概念理解" in chunks[0]
    assert captured["answer"].intent == "clarify"
    assert captured["answer"].suggested_directions == ["概念理解", "代码实现", "易错点"]


def test_stream_emits_not_covered_when_no_hits(monkeypatch):
    from edu_agent.workflows.kb_qa import workflow as kb_qa_module

    _patch_llm_chain(monkeypatch, error=AssertionError("未覆盖不应调模型"))
    captured: dict = {}

    chunks = list(
        kb_qa_module.stream_kb_qa_answer(
            "量子纠缠的贝尔不等式", on_path=lambda ans: captured.setdefault("answer", ans)
        )
    )
    assert "知识库暂未覆盖" in chunks[0]
    assert captured["answer"].intent == "not_covered"
    assert captured["answer"].diagnosis_hint


def test_stream_mock_mode_yields_mock_text(monkeypatch):
    from edu_agent.workflows.kb_qa import workflow as kb_qa_module

    _patch_llm_chain(monkeypatch, error=AssertionError("演示模式不应调模型"))
    captured: dict = {}

    chunks = list(
        kb_qa_module.stream_kb_qa_answer(
            "二叉树的前序遍历怎么写",
            knowledge_base=_make_kb(),
            mock=True,
            on_path=lambda ans: captured.setdefault("answer", ans),
        )
    )
    assert chunks[0].startswith("**结论**")
    assert "演示模式" in chunks[0]
    assert captured["answer"].mock is True
    assert captured["answer"].citations


def test_stream_real_model_yields_token_by_token(monkeypatch):
    """真实模型路径：生成器应 yield 多个 token，并触发 on_path 预占位。"""

    class FakeChain:
        def __init__(self, tokens):
            self._tokens = tokens

        def stream(self, values):
            for token in self._tokens:
                yield token

    class FakePrompt:
        def __or__(self, llm):
            return FakeChain(["结论：OK", "，", "继续", "！"])

    class FakePromptTemplate:
        @staticmethod
        def from_template(text):
            return FakePrompt()

    from edu_agent.workflows.kb_qa import workflow as kb_qa_module

    monkeypatch.setattr(kb_qa_module, "ChatPromptTemplate", FakePromptTemplate)
    monkeypatch.setattr(kb_qa_module, "get_kb_llm", lambda *a, **k: object())

    captured: dict = {}
    chunks = list(
        kb_qa_module.stream_kb_qa_answer(
            "BKT 是什么",
            knowledge_base=_make_kb(),
            mock=False,
            on_path=lambda ans: captured.setdefault("answer", ans),
        )
    )
    # 真实模型路径应 yield 多个 token（逐 token 流式）
    assert len(chunks) >= 3
    assert "".join(chunks) == "结论：OK，继续！"
    # 预占位的 answer 应有 citations 和元信息
    assert captured["answer"].intent == "kb_answered"
    assert captured["answer"].mock is False
    assert captured["answer"].citations


def test_stream_citations_consistent_with_block_path():
    """流式路径和整段路径产出的引用块应一致（避免两种实现漂移）。"""
    from edu_agent.workflows.kb_qa import workflow as kb_qa_module

    chunks = list(
        kb_qa_module.stream_kb_qa_answer(
            "二叉树的前序遍历怎么写",
            knowledge_base=_make_kb(),
            mock=True,
        )
    )
    mock_text = "".join(chunks)
    full_answer = kb_qa_module.run_kb_qa_workflow(
        "二叉树的前序遍历怎么写",
        knowledge_base=_make_kb(),
        mock=True,
    )
    assert mock_text == full_answer.answer_markdown
