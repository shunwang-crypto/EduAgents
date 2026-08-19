"""Adaptive Rich Explanation 领域模型。

Explanation 由前端可渲染的 blocks 组成，但 blocks 不是篇幅或段落数量的
约束。一个简单知识点可以只有几个短 block，复杂知识点可以包含很长的
Markdown、代码、图示、表格和公式。

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
    DIAGRAM = "diagram"
    IMAGE = "image"
    TABLE = "table"
    FORMULA = "formula"


# 候选 section 池（不是固定模板）。
#
# 这两个列表只回答「这类内容通常会用到哪些 section」，不规定必须全用、
# 不规定顺序、也不规定数量。生成器把它们作为候选交给 LLM，LLM 按知识点
# 复杂度自行取舍：简单知识点可以只用两三个，复杂知识点可以增加 diagram /
# table / formula / image / contrast，并重新排序。
CODE_BLOCK_CANDIDATES = [
    "orientation",
    "big_picture",
    "concept",
    "diagram",
    "code_walkthrough",
    "worked_example",
    "table",
    "misconception",
    "application",
    "recap",
    "handoff",
]
THEORY_BLOCK_CANDIDATES = [
    "orientation",
    "big_picture",
    "concept",
    "diagram",
    "formula",
    "contrast",
    "table",
    "worked_example",
    "misconception",
    "application",
    "recap",
    "handoff",
]


class ExplanationBlock(BaseModel):
    """一个结构化的教学区段。

    ``data`` 为每个 block 专属结构：
    - big_picture: {"items": [str]} 或 {"nodes":[str],"edges":[str,"str"]}
    - code_walkthrough: {"code": str, "annotations": [{"line":int,"label":str,"explanation":str}]}
    - concept/worked_example/misconception/application: {"content": str, "steps": [str]}
    - recap: {"points": [str]}
    - handoff: {"objective": str, "difficulty": str}
    - orientation/contrast: {"content": str}
    - diagram: {"nodes": [{"id": str, "label": str}], "edges": [{"source": str, "target": str}]}
    - image: {"url": str, "alt": str, "caption": str}
    - table: {"headers": [str], "rows": [[str]]}
    - formula: {"latex": str, "explanation": str}

    ``content`` intentionally remains an unrestricted Markdown string. The
    schema describes rendering, not the amount of teaching material: a single
    block may legitimately hold several thousand characters of Markdown with
    headings, lists, fenced code and LaTeX.
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
    schema_version: int = 2

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
