import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.core.agent_runner import normalize_markdown_output  # noqa: E402
from edu_agent.core.agent_runner import model_to_text  # noqa: E402


def test_normalize_markdown_output_unwraps_content_json():
    raw = '{"content": "# 标题\\n\\n## 小节\\n内容"}'

    assert normalize_markdown_output(raw) == "# 标题\n\n## 小节\n内容"


def test_normalize_markdown_output_strips_code_fence():
    raw = "```markdown\n# 标题\n\n内容\n```"

    assert normalize_markdown_output(raw) == "# 标题\n\n内容"


def test_normalize_markdown_output_strips_provider_thought_wrapper():
    raw = "<thought>internal reasoning that must not be shown</thought># 标题\n\n正文"
    assert normalize_markdown_output(raw) == "# 标题\n\n正文"


def test_model_to_text_extracts_ai_message_content():
    from langchain_core.messages import AIMessage

    assert model_to_text(AIMessage(content="# 标题")) == "# 标题"
