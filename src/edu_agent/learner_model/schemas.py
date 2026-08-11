"""本地 Dynamic Learner Model 领域模型（SQLite 是唯一 Source of Truth）。

范围收缩后保留的实体：
- Profile / Goal / Preferences / KnowledgeItem / CourseLearnerState / LearnerStateBundle
- LearningContext（统一上下文）
删除：AbilityItem / Misconception / BehaviorState / Evidence（无消费方）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

StateFreshness = str  # 本地模型恒为 fresh，保留 str 类型占位
KnowledgeStatus = str  # weak/learning/mastered/unknown
Trend = Optional[str]  # improving/declining/stable/unknown


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Profile(BaseModel):
    user_id: str = Field(default="")
    display_name: str = Field(default="")
    education_level: str = Field(default="")
    language: str = Field(default="zh")
    background: str = Field(default="")


class Goal(BaseModel):
    goal_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_name: str = Field(default="")
    target: str = Field(default="")
    priority: int = Field(default=1)
    status: str = Field(default="active")
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    target_kcs: List[str] = Field(default_factory=list)


class ModeScore(BaseModel):
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    sample_size: int = Field(default=0)


class Preferences(BaseModel):
    preferred_mode: str = Field(default="")
    mode_effectiveness: Dict[str, ModeScore] = Field(default_factory=dict)
    pace_factor: float = Field(default=1.0, ge=0.1, le=3.0)
    scaffold_preference: float = Field(default=0.5, ge=0.0, le=1.0)


class SemanticMemoryItem(BaseModel):
    content: str = Field(default="")
    created_at: str = Field(default="")


class GlobalLearnerState(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    goals: List[Goal] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
    semantic_memory: List[SemanticMemoryItem] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    """单个 KC 状态。mastery=None = UNKNOWN（从未有证据），不是 0。"""

    kc_id: str = Field(default="")
    name: str = Field(default="")
    mastery: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None)
    status: str = Field(default="unknown")
    trend: Optional[str] = Field(default=None)
    evidence_count: Optional[int] = Field(default=None)
    last_evidence_at: Optional[str] = Field(default=None)
    is_estimated: bool = Field(default=False)


class CourseLearnerState(BaseModel):
    schema_version: int = Field(default=1)
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    knowledge: List[KnowledgeItem] = Field(default_factory=list)
    metadata: Dict[str, object] = Field(default_factory=dict)
    state_version: Optional[int] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)
    freshness: str = Field(default="fresh")

    def knowledge_map(self) -> Dict[str, KnowledgeItem]:
        return {item.kc_id: item for item in self.knowledge}

    def get_knowledge(self, kc_id: str) -> Optional[KnowledgeItem]:
        return self.knowledge_map().get(kc_id)


class LearnerStateBundle(BaseModel):
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    global_state: GlobalLearnerState = Field(default_factory=GlobalLearnerState)
    course_state: CourseLearnerState = Field(default_factory=CourseLearnerState)
    active_goal: Optional[Goal] = Field(default=None)
    global_state_version: Optional[int] = Field(default=None)
    course_state_version: Optional[int] = Field(default=None)

    @property
    def bundle_version(self) -> dict:
        return {"global": self.global_state_version, "course": self.course_state_version}


class LearningContext(BaseModel):
    """统一学习上下文：所有业务（Service/Event/Workflow）必须使用它，禁止默认 course 污染。"""

    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    session_id: str = Field(default="")
