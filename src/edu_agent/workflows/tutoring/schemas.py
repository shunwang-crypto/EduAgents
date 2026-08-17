"""Tutoring Workflow 的核心数据结构（Pydantic）。

所有 Agent（Planner / Tutor / Diagnoser）的输入输出都基于这里的 schema，
便于结构化校验与确定性回退。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Teaching Action
# ---------------------------------------------------------------------------


class TeachingAction(str, Enum):
    """教学动作枚举。默认进入未知 KC 使用 ASSESS。"""

    ASSESS = "ASSESS"
    PROBE = "PROBE"
    HINT = "HINT"
    EXPLAIN = "EXPLAIN"
    EXAMPLE = "EXAMPLE"
    COMPARE = "COMPARE"
    PRACTICE = "PRACTICE"
    FEEDBACK = "FEEDBACK"
    REFLECT = "REFLECT"
    CHALLENGE = "CHALLENGE"
    APPLICATION = "APPLICATION"


# ---------------------------------------------------------------------------
# 结构化输入
# ---------------------------------------------------------------------------


class LearnerKCSnapshot(BaseModel):
    """单个 KC 的 learner state 快照（供 Agent 决策使用）。"""

    kc_id: str
    mastery: Optional[float] = None       # None = 未评估（UNKNOWN）
    confidence: Optional[float] = None
    status: str = "unknown"               # unknown/weak/learning/mastered
    misconceptions: List[str] = Field(default_factory=list)
    recent_evidence: List["EvidenceItem"] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """一条学习证据（最小结构，复用 learning_events）。"""

    kc_id: str
    evidence_type: str                    # concept_question / practice / coding / quiz ...
    correctness: Optional[str] = None     # correct / partial / incorrect / None
    difficulty: int = 1
    hint_level: int = 0
    confidence: Optional[float] = None
    misconceptions: List[str] = Field(default_factory=list)
    source: str = "tutor"
    timestamp: Optional[str] = None
    interaction_id: Optional[str] = None


class TutorRequest(BaseModel):
    """POST /api/courses/{course_id}/tutor/turn 的请求体。"""

    kc_id: str
    message: Optional[str] = None          # None = 开始 / 下一轮教学
    learning_goal: Optional[str] = None
    difficulty: int = 1


# ---------------------------------------------------------------------------
# Planner 输出
# ---------------------------------------------------------------------------


class PlannerDecision(BaseModel):
    """Planner 决策：下一步学哪个 KC + 用什么 Teaching Action。"""

    selected_kc: str
    teaching_action: TeachingAction
    difficulty: int = 1
    reason_codes: List[str] = Field(default_factory=list)
    rationale: str = ""                    # 给前端的"为什么推荐"（非 CoT）


# ---------------------------------------------------------------------------
# Diagnoser 输出
# ---------------------------------------------------------------------------


class Diagnosis(BaseModel):
    """Diagnoser 对 learner 回复的结构化诊断。"""

    kc_id: str
    correctness: str = "incorrect"         # correct / partial / incorrect
    confidence: float = 0.5                # 诊断本身置信度
    evidence_strength: str = "medium"      # weak / medium / strong
    misconceptions: List[str] = Field(default_factory=list)
    hint_level: int = 0
    difficulty: int = 1
    note: str = ""


# ---------------------------------------------------------------------------
# Tutor 输出
# ---------------------------------------------------------------------------


class TutorResponse(BaseModel):
    """Tutor 面向用户的一轮教学消息 + 状态变化摘要。"""

    kc_id: str
    teaching_action: TeachingAction
    message: str
    learner_state_changed: bool = False
    learning_map_changed: bool = False
    mastery: Optional[float] = None
    confidence: Optional[float] = None
    reason_codes: List[str] = Field(default_factory=list)
    next_recommended_kc: Optional[str] = None
    # 给前端展示的"为什么"（非 Chain of Thought）
    explanation: str = ""


LearnerKCSnapshot.model_rebuild()
EvidenceItem.model_rebuild()
