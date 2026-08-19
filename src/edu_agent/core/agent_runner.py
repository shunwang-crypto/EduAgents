import json
from typing import Any, Type

from pydantic import BaseModel

try:
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover - keeps lightweight imports usable before install
    BaseMessage = None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if "content" in content:
            return _content_to_text(content["content"])
        if "text" in content:
            return _content_to_text(content["text"])
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        return "\n".join(_content_to_text(item) for item in content)
    return str(content)


def model_to_text(value: Any) -> str:
    """Convert LangChain/Pydantic outputs into displayable text."""

    if BaseMessage is not None and isinstance(value, BaseMessage):
        return _content_to_text(value.content)
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(), ensure_ascii=False, indent=2)
    return str(value)


def normalize_markdown_output(value: Any) -> str:
    """Unwrap common model/provider wrappers and return clean Markdown text."""

    text = model_to_text(value).strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    for _ in range(2):
        candidate = text.strip()
        if not (candidate.startswith("{") and candidate.endswith("}")):
            break
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            break
        if isinstance(data, dict):
            for key in ("content", "final_plan_markdown", "plan_markdown", "text"):
                if key in data:
                    text = _content_to_text(data[key]).strip()
                    break
            else:
                break
        else:
            break

    return text.replace("\\n", "\n").strip()


def invoke_structured_output(
    prompt_text: str,
    schema: Type[BaseModel],
    values: dict,
    llm: Any,
) -> BaseModel:
    """Ask a model for JSON and parse it locally instead of relying on provider response_format."""

    # OFFLINE 测试模式：跳过真实 LLM 调用，立即触发调用方的确定性 fallback，
    # 避免在无 API 环境下等待超时。仅影响 EDU_OFFLINE=1 的测试路径。
    import os as _os
    if _os.environ.get("EDU_OFFLINE", "").strip() in ("1", "true", "True"):
        raise RuntimeError("EDU_OFFLINE: skipping LLM call")

    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    parser = PydanticOutputParser(pydantic_object=schema)
    prompt = ChatPromptTemplate.from_template(
        prompt_text
        + """

请严格输出一个 JSON 对象，不要输出 Markdown 代码块，不要添加解释文字。
JSON 必须符合下面的结构说明：

{format_instructions}
"""
    )
    response = (prompt | llm).invoke(
        {
            **values,
            "format_instructions": parser.get_format_instructions(),
        }
    )
    return parser.parse(model_to_text(response))
