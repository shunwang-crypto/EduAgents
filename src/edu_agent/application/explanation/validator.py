"""Adaptive Rich Explanation Validator。

校验 block type、标题和练习/判题禁用语。这里不按固定 section 数量或
字数裁剪内容；结构由知识点复杂度和教学目标决定。
生产代码禁止出现 exercise/grading 语义（见 tests/test_no_exercise.py）。
"""

from __future__ import annotations

from typing import List

from edu_agent.application.explanation.models import (
    BlockType,
    ExplanationBlock,
    StepExplanation,
)

# 判定为“练习/判题”的禁用内容（允许出现在“禁止”语境之外时不得产出）
_FORBIDDEN = [
    "correct_answer",
    "submitted_answer",
    "score",
    "grading",
    "quiz",
    "options",
    "answers",
]


class ValidationIssue:
    def __init__(self, message: str) -> None:
        self.message = message


class ExplanationValidator:
    def validate(self, explanation: StepExplanation) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        if not explanation.title.strip():
            issues.append(ValidationIssue("title is empty"))
        if not explanation.blocks:
            issues.append(ValidationIssue("blocks is empty"))
            return issues
        seen_titles: set = set()
        for b in explanation.blocks:
            self._validate_block(b, issues, seen_titles)
        return issues

    def _validate_block(
        self, block: ExplanationBlock, issues: List[ValidationIssue], seen_titles: set
    ) -> None:
        if not isinstance(block.type, BlockType) or block.type not in BlockType:
            issues.append(ValidationIssue(f"invalid block type: {block.type}"))
        if not block.title.strip():
            issues.append(ValidationIssue(f"block ({block.type}) missing title"))
        title_key = (block.type.value, block.title.strip())
        if title_key in seen_titles:
            issues.append(ValidationIssue(f"duplicate block: {block.type.value}:{block.title}"))
        seen_titles.add(title_key)

        text = self._flatten(block)
        lowered = text.lower()
        for word in _FORBIDDEN:
            if word in lowered:
                issues.append(ValidationIssue(f"forbidden practice content: {word}"))

    @staticmethod
    def _flatten(block: ExplanationBlock) -> str:
        parts = [block.content or ""]

        def visit(value) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)
            elif value is not None:
                parts.append(str(value))

        visit(block.data or {})
        return "\n".join(parts)
