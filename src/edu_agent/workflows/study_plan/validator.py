import re
from typing import Any

from edu_agent.workflows.study_plan.resource_rules import resources_look_relevant
from edu_agent.workflows.study_plan.schemas import (
    DraftPlan,
    EvaluatedResearchResult,
    PlanValidationResult,
    ResearchResult,
    StudentInput,
)


VAGUE_EXPRESSIONS = (
    "多看资料",
    "加强练习",
    "深入理解",
    "认真学习",
    "多做项目",
    "基本掌握",
    "熟悉了解",
)

CHECKED_RULES = [
    "包含计划摘要",
    "包含学习内容拆解",
    "包含阶段安排",
    "包含每日学习计划",
    "每日计划天数等于学习周期",
    "每日计划包含学习任务、实践任务、检查方式",
    "包含练习任务",
    "包含最终验收标准",
    "不存在空泛表达",
    "未联网时不编造具体 URL",
    "每天任务量不明显超过可用时间",
    "推荐资源和学习主题相关",
]


def _extract_section(markdown: str, keyword: str) -> str:
    start = markdown.find(keyword)
    if start < 0:
        return ""
    next_match = re.search(r"\n##\s+", markdown[start + len(keyword):])
    if not next_match:
        return markdown[start:]
    return markdown[start:start + len(keyword) + next_match.start()]


def _extract_daily_section(markdown: str) -> str:
    section = _extract_section(markdown, "每日学习计划")
    if section:
        return section
    return _extract_section(markdown, "每日学习安排")


def _extract_day_numbers(daily_section: str) -> set[int]:
    day_numbers = {
        int(match)
        for match in re.findall(r"(?:第\s*)?(\d{1,3})\s*天", daily_section)
    }

    for line in daily_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] in {"天数", "阶段/天数"}:
            continue
        match = re.search(r"\d{1,3}", cells[0])
        if match:
            day_numbers.add(int(match.group()))

    return day_numbers


def _daily_table_rows(daily_section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in daily_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] in {"天数", "阶段/天数"}:
            continue
        if not re.search(r"\d{1,3}", cells[0]):
            continue
        rows.append(cells)
    return rows


def _parse_minutes(text: str) -> float | None:
    matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(小时|小時|h|hour|hours|分钟|分鐘|分|min|mins|minute|minutes)",
        text,
        flags=re.IGNORECASE,
    )
    if not matches:
        return None

    total = 0.0
    for value, unit in matches:
        number = float(value)
        unit_lower = unit.lower()
        if unit_lower in {"小时", "小時", "h", "hour", "hours"}:
            total += number * 60
        else:
            total += number
    return total


def _daily_time_limit_minutes(daily_time: str) -> float | None:
    parsed = _parse_minutes(daily_time)
    if parsed is not None:
        return parsed

    match = re.search(r"\d+(?:\.\d+)?", daily_time)
    if not match:
        return None
    value = float(match.group())
    return value * 60 if value <= 12 else value


def _lines_with_obvious_daily_duration(daily_section: str) -> list[tuple[str, float]]:
    lines = []
    for line in daily_section.splitlines():
        if not re.search(r"(?:第\s*)?\d{1,3}\s*天|\|\s*\d{1,3}\s*\|", line):
            continue
        minutes = _parse_minutes(line)
        if minutes is not None:
            lines.append((line, minutes))
    return lines


def _has_url(markdown: str) -> bool:
    return bool(re.search(r"https?://[^\s)]+", markdown))


def _resources_from(research: Any) -> list[Any]:
    return list(getattr(research, "resources", []) or [])


def validate_study_plan(
    student_input: StudentInput,
    draft_plan: DraftPlan,
    research: ResearchResult | EvaluatedResearchResult,
) -> PlanValidationResult:
    markdown = draft_plan.plan_markdown or ""
    daily_section = _extract_daily_section(markdown)
    day_numbers = _extract_day_numbers(daily_section)
    daily_rows = _daily_table_rows(daily_section)
    issues: list[str] = []
    suggestions: list[str] = []

    if "计划摘要" not in markdown:
        issues.append("计划缺少“计划摘要”章节。")
        suggestions.append("补充包含学习主题、周期、每日时间、当前基础、目标和联网状态的摘要表。")

    if "学习内容拆解" not in markdown:
        issues.append("计划缺少“学习内容拆解”章节。")
        suggestions.append("加入前置知识、核心知识点、推荐学习顺序和可能难点。")

    if "阶段安排" not in markdown:
        issues.append("计划缺少“阶段安排”章节。")
        suggestions.append("用阶段表覆盖整个学习周期，并为每个阶段写明可检查产出。")

    if not daily_section:
        issues.append("计划缺少“每日学习计划”章节。")
        suggestions.append("补充按天展开的学习计划表。")
    elif day_numbers != set(range(1, student_input.days + 1)):
        missing_days = sorted(set(range(1, student_input.days + 1)) - day_numbers)
        extra_days = sorted(day_numbers - set(range(1, student_input.days + 1)))
        issues.append(
            f"每日计划天数和输入的 {student_input.days} 天不一致。"
        )
        detail = []
        if missing_days:
            detail.append(f"缺少第 {', '.join(map(str, missing_days))} 天")
        if extra_days:
            detail.append(f"存在超出周期的第 {', '.join(map(str, extra_days))} 天")
        suggestions.append(
            "补齐缺失天数或合并多余天数，确保每日计划正好覆盖第 1 天到第 "
            f"{student_input.days} 天。{'；'.join(detail)}"
        )

    required_daily_columns = ("学习任务", "实践任务", "检查方式")
    missing_columns = [
        column for column in required_daily_columns if column not in daily_section
    ]
    if missing_columns:
        issues.append(f"每日计划缺少字段：{', '.join(missing_columns)}。")
        suggestions.append("每日计划必须同时包含学习任务、实践任务和检查方式。")
    elif daily_rows:
        incomplete_rows = []
        for row in daily_rows:
            if len(row) < 5 or not row[2] or not row[3] or not row[4]:
                incomplete_rows.append(row[0])
        if incomplete_rows:
            issues.append(
                f"部分每日计划未填写学习任务、实践任务或检查方式：{', '.join(incomplete_rows)}。"
            )
            suggestions.append("逐日补齐具体学习动作、可执行实践任务和可判断的检查方式。")

    if "最终验收标准" not in markdown:
        issues.append("计划缺少“最终验收标准”章节。")
        suggestions.append("补充 4 到 6 条可检查的最终验收标准。")

    vague_hits = [phrase for phrase in VAGUE_EXPRESSIONS if phrase in markdown]
    if vague_hits:
        issues.append(f"计划存在空泛表达：{', '.join(vague_hits)}。")
        suggestions.append("将空泛表达替换为具体动作、产出物或检查标准。")

    if not research.search_enabled and _has_url(markdown):
        issues.append("未启用联网搜索时，计划中出现了具体 URL。")
        suggestions.append("未联网时只给资源类型建议，不要写具体链接。")

    limit_minutes = _daily_time_limit_minutes(student_input.daily_time)
    if limit_minutes:
        over_limit_lines = [
            line
            for line, minutes in _lines_with_obvious_daily_duration(daily_section)
            if minutes > limit_minutes * 1.15
        ]
        if over_limit_lines:
            issues.append("部分每日任务的预计时间明显超过学生每天可投入时间。")
            suggestions.append("压缩当天任务，或把拓展内容移到可选任务。")

    resources = _resources_from(research)
    if research.search_enabled and resources:
        if not resources_look_relevant(student_input.topic, resources):
            issues.append("推荐资源和学习主题的相关性较弱。")
            suggestions.append("优先保留标题、摘要或链接中能对应学习主题与核心知识点的资源。")

    return PlanValidationResult(
        passed=not issues,
        issues=issues,
        suggestions=suggestions,
        checked_rules=CHECKED_RULES,
    )
