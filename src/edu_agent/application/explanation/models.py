"""Structured Explanation 领域模型（替换旧 lesson_markdown 长文）。

Explanation 由有限的 ``ExplanationBlock`` 组成，每个 block 只聚焦一个教学目的。
这不是 Markdown article，也不是 chat messages，而是可导航的结构化教学步骤。

Exercise / grading 严格不属于本模块（见 tests/test_no_exercise.py 契约）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class BlockType(str, Enum):
    ORIENTATION = "orientation"
    BIG_PICTURE = "big_picture"
    CONCEPT = "concept"
    WORKED_EXAMPLE = "worked_example"
    CODE_WALKTHROUGH = "code_walkthrough"
    CONTRAST = "contrast"
    MISCONCEPTION = "misconception"
    APPLICATION = "application"
    RECAP = "recap"
    HANDOFF = "handoff"


# 合法 block 顺序模板（编程课程 / 理论课程，Planner 可据此裁剪）
CODE_BLOCK_ORDER = [
    "orientation",
    "big_picture",
    "concept",
    "code_walkthrough",
    "worked_example",
    "misconception",
    "application",
    "recap",
    "handoff",
]
THEORY_BLOCK_ORDER = [
    "orientation",
    "big_picture",
    "concept",
    "contrast",
    "worked_example",
    "misconception",
    "application",
    "recap",
    "handoff",
]


class ExplanationBlock(BaseModel):
    """一个结构化的教学步骤。

    ``data`` 为每个 block 专属结构：
    - big_picture: {"items": [str]} 或 {"nodes":[str],"edges":[str,"str"]}
    - code_walkthrough: {"code": str, "annotations": [{"line":int,"label":str,"explanation":str}]}
    - concept/worked_example/misconception/application: {"content": str, "steps": [str]}
    - recap: {"points": [str]}
    - handoff: {"objective": str, "difficulty": str}
    - orientation/contrast: {"content": str}
    """

    type: BlockType
    title: str
    content: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    source_refs: List[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("explanation block title must not be empty")
        return v


class StepExplanation(BaseModel):
    """一个 PlanStep / KC 的完整结构化讲解。"""

    explanation_id: str
    course_id: str
    plan_id: str
    step_id: str
    kc_id: str
    schema_version: int = 1

    title: str
    objective: str = ""
    estimated_minutes: int = 0

    blocks: List[ExplanationBlock] = Field(default_factory=list)

    context_hash: str = ""
    generated_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Practice Handoff（只定义接口，不实现练习）
# ---------------------------------------------------------------------------


class PracticeHandoff(BaseModel):
    """进入外部 Practice / Assessment 模块的接口契约。

    本模块只产出 handoff 入口，绝不生成题目 / 判分（见 test_no_exercise）。
    """

    course_id: str
    plan_id: str
    step_id: str
    kc_id: str
    learning_objective: str = ""
    recommended_difficulty: str = "medium"
    source: str = "study_plan"
    return_url: str = ""
