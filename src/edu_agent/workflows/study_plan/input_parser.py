import re
from typing import Any

from pydantic import BaseModel, Field

from edu_agent.core.agent_runner import invoke_structured_output
from edu_agent.core.llm import get_llm
from edu_agent.workflows.study_plan.prompts import INPUT_PARSER_PROMPT


class ParsedStudentInput(BaseModel):
    topic: str = Field(default="", description="学生想学习的内容")
    level: str = Field(default="", description="学生当前基础")
    days: int | None = Field(default=None, description="学习周期，单位：天")
    daily_time: str = Field(default="", description="每天可投入学习时间")
    goal: str = Field(default="", description="学生学习目标")
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段")


FIELD_LABELS = {
    "topic": "学习内容",
    "level": "当前基础",
    "days": "学习周期",
    "daily_time": "每天学习时间",
    "goal": "学习目标",
}

SEGMENT_SPLIT_RE = re.compile(r"[，,；;\n。]+")
DAY_RE = re.compile(r"(\d{1,3})\s*(?:天|日|d|day|days)", re.IGNORECASE)
WEEK_RE = re.compile(r"(\d{1,2})\s*(?:周|星期|week|weeks)", re.IGNORECASE)
DAILY_TIME_RE = re.compile(
    r"(?:每天|每日|一天|每晚|每天下班后|daily|per day)?\s*"
    r"(\d+(?:\.\d+)?)\s*"
    r"(小时|小時|h|hour|hours|分钟|分鐘|分|min|mins|minute|minutes)",
    re.IGNORECASE,
)


def _clean_value(value: str) -> str:
    value = value.strip(" ：:，,；;。.\n\t")
    value = re.sub(r"^(我想|我要|想要|希望|计划|打算|需要|准备)", "", value)
    return value.strip(" ：:，,；;。.\n\t")


def _extract_by_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_value(match.group(1))
    return ""


def _segments(text: str) -> list[str]:
    return [_clean_value(segment) for segment in SEGMENT_SPLIT_RE.split(text) if _clean_value(segment)]


def _extract_topic(text: str, segments: list[str]) -> str:
    topic = _extract_by_patterns(
        text,
        [
            r"(?:学习内容|学习主题|想学习|想学|学习|主题|学)\s*(?:是|为|:|：)?\s*([^，,；;。\n]+)",
            r"(?:我要|我想|想要|希望|计划|打算|准备)\s*(?:学习|学)\s*([^，,；;。\n]+)",
        ],
    )
    if topic:
        return topic

    for segment in segments:
        if any(keyword in segment for keyword in ("基础", "目标", "每天", "每日", "周期", "天", "小时", "分钟")):
            continue
        return segment
    return ""


def _extract_after_marker(
    text: str,
    markers: tuple[str, ...],
    stop_markers: tuple[str, ...],
) -> str:
    starts = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    if not starts:
        return ""
    start = min(starts)
    value_start = start
    for marker in markers:
        if text.startswith(marker, start):
            value_start = start + len(marker)
            break

    stop_positions = [
        text.find(marker, value_start)
        for marker in stop_markers
        if text.find(marker, value_start) >= 0
    ]
    value_end = min(stop_positions) if stop_positions else len(text)
    return _clean_value(text[value_start:value_end])


def _trim_level_value(value: str) -> str:
    parts = re.split(
        r"[，,；;]\s*(?:\d{1,3}\s*(?:天|日|周|星期|week|weeks)|每天|每日|目标|学习目标|最终目标)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    return _clean_value(parts[0])


def _extract_level(text: str) -> str:
    explicit = _extract_after_marker(
        text,
        ("当前基础是", "当前基础：", "当前基础:", "基础是", "基础：", "基础:", "我会", "已有基础是"),
        ("每天", "每日", "学习周期", "周期", "目标是", "目标：", "目标:", "学习目标", "最终目标"),
    )
    if explicit:
        return _trim_level_value(explicit)

    level = _extract_by_patterns(
        text,
        [
            r"(?:当前基础|基础|水平|已有基础|现在会|目前会)\s*(?:是|为|:|：)?\s*([^，,；;。\n]+)",
            r"(零基础|没有基础|无基础|会[^，,；;。\n]*)",
        ],
    )
    return _trim_level_value(level) if level else ""


def _extract_days(text: str) -> int | None:
    day_match = DAY_RE.search(text)
    if day_match:
        return int(day_match.group(1))

    week_match = WEEK_RE.search(text)
    if week_match:
        return int(week_match.group(1)) * 7

    return None


def _extract_daily_time(text: str) -> str:
    for segment in _segments(text):
        match = DAILY_TIME_RE.search(segment)
        if not match:
            continue
        if any(keyword in segment for keyword in ("每天", "每日", "一天", "每晚", "daily", "per day")):
            return f"{match.group(1)} {match.group(2)}"

    match = DAILY_TIME_RE.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return ""


def _extract_goal(text: str) -> str:
    explicit = _extract_after_marker(
        text,
        ("学习目标是", "学习目标：", "学习目标:", "目标是", "目标：", "目标:", "最终目标是", "最终能"),
        (),
    )
    if explicit:
        return explicit

    return _extract_by_patterns(
        text,
        [
            r"(?:学习目标|目标|希望达到|想达到|为了|用来|最终能|能够|能)\s*(?:是|为|:|：)?\s*([^，,；;。\n]+)",
        ],
    )


def _missing_fields(data: dict[str, Any]) -> list[str]:
    missing = []
    for field_name, label in FIELD_LABELS.items():
        value = data.get(field_name)
        if value is None or value == "":
            missing.append(label)
    return missing


def _normalize_parsed_result(parsed: ParsedStudentInput) -> ParsedStudentInput:
    data = parsed.model_dump()
    for key in ("topic", "level", "daily_time", "goal"):
        data[key] = _clean_value(str(data.get(key) or ""))
    if data.get("days") is not None:
        try:
            data["days"] = int(data["days"])
        except (TypeError, ValueError):
            data["days"] = None
    data["missing_fields"] = _missing_fields(data)
    return ParsedStudentInput(**data)


def parse_student_input(text: str) -> ParsedStudentInput:
    """Parse a one-sentence learning request into form-friendly fields."""

    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return ParsedStudentInput(missing_fields=list(FIELD_LABELS.values()))

    segments = _segments(normalized)
    data: dict[str, Any] = {
        "topic": _extract_topic(normalized, segments),
        "level": _extract_level(normalized),
        "days": _extract_days(normalized),
        "daily_time": _extract_daily_time(normalized),
        "goal": _extract_goal(normalized),
    }
    data["missing_fields"] = _missing_fields(data)
    return _normalize_parsed_result(ParsedStudentInput(**data))


def input_parser_agent(text: str) -> ParsedStudentInput:
    """
    InputParser Agent:
    Use LLM structured parsing first, then fall back to deterministic parsing.
    """

    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return ParsedStudentInput(missing_fields=list(FIELD_LABELS.values()))

    fallback = parse_student_input(normalized)
    try:
        parsed = invoke_structured_output(
            INPUT_PARSER_PROMPT,
            ParsedStudentInput,
            {"user_text": normalized},
            get_llm(temperature=0.0),
        )
        parsed = _normalize_parsed_result(parsed)
        if not parsed.missing_fields:
            return parsed
        if len(parsed.missing_fields) < len(fallback.missing_fields):
            return parsed
        if not fallback.topic and parsed.topic:
            return parsed
        if not fallback.level and parsed.level:
            return parsed
        if not fallback.goal and parsed.goal:
            return parsed
        return fallback
    except Exception:  # noqa: BLE001 - quick input should keep working without LLM
        return fallback
