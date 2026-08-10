"""内部 LearnerState 领域模型（EduAgents 侧的唯一画像契约）。

设计原则（与架构文档一致）：
- 这里是 LearnerState 的 Source of Truth（只读消费）。
- EduAgents 禁止在本地再维护一套 student_profile / mastery 变更。
- Mastery 与 Confidence 必须分离：
    mastery=.20 + confidence=.95  → 基本确定学生不会；
    mastery=.20 + confidence=.15  → 数据不足，不能武断。
- 多课程隔离：所有状态都带 user_id + course_id。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# 课程状态新鲜度
StateFreshness = Literal["fresh", "stale", "mock", "missing"]

KnowledgeStatus = Literal["weak", "learning", "mastered", "unknown"]
Trend = Literal["improving", "declining", "stable", "unknown"]
MisconceptionType = Literal[
    "conceptual_confusion", "formula_error", "calc_slip", "misread", "knowledge_gap"
]
MisconceptionStatus = Literal["active", "resolved", "dormant"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 用户级 Global State
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    """相对稳定的用户信息，不放任何课程级掌握度。"""

    user_id: str = Field(default="", description="用户唯一标识")
    display_name: str = Field(default="", description="显示名")
    education_level: str = Field(default="", description="学历/年级")
    language: str = Field(default="zh", description="语言")
    background: str = Field(default="", description="背景描述（职业/经历等）")


class Goal(BaseModel):
    """一个学习目标。用户可以同时拥有多个目标。"""

    goal_id: str = Field(default="", description="目标 ID")
    course_id: str = Field(default="", description="目标所属课程")
    goal_name: str = Field(default="", description="目标名称")
    target: str = Field(default="", description="目标描述")
    priority: int = Field(default=1, description="优先级，越小越优先")
    status: str = Field(default="active", description="active/completed/paused")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="目标进度 0-1")
    target_kcs: List[str] = Field(default_factory=list, description="目标关联 KC ID 列表")


class ModeScore(BaseModel):
    """某种教学模式的实测效果（带置信度与样本量），替代单一风格标签。"""

    score: float = Field(default=0.0, ge=0.0, le=1.0, description="该模式的历史有效性")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度")
    sample_size: int = Field(default=0, description="样本量")


class Preferences(BaseModel):
    """跨课程长期偏好，基于历史真实教学效果而非永久风格标签。"""

    preferred_mode: str = Field(default="", description="首选模式，如 worked_example")
    learning_style_distribution: Dict[str, float] = Field(
        default_factory=dict, description="风格分布，如 {example_driven: 0.8}"
    )
    mode_effectiveness: Dict[str, ModeScore] = Field(
        default_factory=dict, description="各模式实测效果"
    )
    pace_factor: float = Field(default=1.0, ge=0.1, le=3.0, description="节奏系数")
    scaffold_preference: float = Field(default=0.5, ge=0.0, le=1.0, description="支架偏好 0-1")


class SemanticMemoryItem(BaseModel):
    """适合语义检索的长期记忆（用户经历/有效类比/熟悉技术栈）。"""

    content: str = Field(default="", description="记忆内容")
    tags: List[str] = Field(default_factory=list, description="检索标签")
    created_at: str = Field(default="", description="创建时间")


class GlobalLearnerState(BaseModel):
    """用户级全局状态：profile + goals + preferences + semantic_memory。"""

    profile: Profile = Field(default_factory=Profile)
    goals: List[Goal] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
    semantic_memory: List[SemanticMemoryItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 课程级 Course Learner State
# ---------------------------------------------------------------------------


class KnowledgeItem(BaseModel):
    """单个 KC 的掌握状态。Mastery 与 Confidence 分离。"""

    kc_id: str = Field(default="", description="知识组件 ID")
    name: str = Field(default="", description="名称")
    mastery: float = Field(default=0.0, ge=0.0, le=1.0, description="掌握度 0-1")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度 0-1")
    status: KnowledgeStatus = Field(default="unknown", description="状态")
    trend: Trend = Field(default="unknown", description="趋势")
    evidence_count: int = Field(default=0, description="证据数")
    last_evidence_at: Optional[str] = Field(default=None, description="最近证据时间")
    is_estimated: bool = Field(default=False, description="是否为估计值")


class AbilityItem(BaseModel):
    """六维能力之一：understanding/application/reasoning/expression/reflection/transfer。"""

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    trend: Trend = Field(default="unknown")
    evidence_count: int = Field(default=0)


class Misconception(BaseModel):
    """结构化错因（替代 mixed×7 式标签）。"""

    misconception_id: str = Field(default="")
    kc_id: str = Field(default="")
    type: MisconceptionType = Field(default="conceptual_confusion")
    description: str = Field(default="")
    severity: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    occurrence_count: int = Field(default=0)
    status: MisconceptionStatus = Field(default="active")
    first_seen_at: Optional[str] = Field(default=None)
    last_seen_at: Optional[str] = Field(default=None)


class BehaviorState(BaseModel):
    """课程相关近期行为聚合。"""

    activity_count_30d: int = Field(default=0)
    streak_days: int = Field(default=0)
    average_session_minutes: float = Field(default=0.0)
    recent_topics: List[str] = Field(default_factory=list)
    frequent_revisited_topics: List[str] = Field(default_factory=list)


class CourseLearnerState(BaseModel):
    """一门课程的学习者状态（EduAgents 最重要的外部输入）。"""

    schema_version: int = Field(default=1)
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="课程进度 0-1")
    knowledge: List[KnowledgeItem] = Field(default_factory=list)
    abilities: Dict[str, AbilityItem] = Field(
        default_factory=dict,
        description="六维能力：understanding/application/reasoning/expression/reflection/transfer",
    )
    misconceptions: List[Misconception] = Field(default_factory=list)
    behavior: BehaviorState = Field(default_factory=BehaviorState)
    metadata: Dict[str, object] = Field(default_factory=dict)

    # 版本与新鲜度（由 Provider 填充，非合作伙伴字段）
    state_version: Optional[int] = Field(default=None, description="画像版本号")
    updated_at: Optional[str] = Field(default=None, description="画像更新时间")
    freshness: StateFreshness = Field(default="fresh", description="fresh/stale/mock/missing")

    def knowledge_map(self) -> Dict[str, KnowledgeItem]:
        return {item.kc_id: item for item in self.knowledge}

    def get_knowledge(self, kc_id: str) -> Optional[KnowledgeItem]:
        return self.knowledge_map().get(kc_id)


class LearnerStateBundle(BaseModel):
    """业务工作流一次拿到的最小上下文集合：全局 + 课程 + 目标。"""

    user_id: str = Field(default="")
    course_id: str = Field(default="")
    global_state: GlobalLearnerState = Field(default_factory=GlobalLearnerState)
    course_state: CourseLearnerState = Field(default_factory=CourseLearnerState)
    active_goal: Optional[Goal] = Field(default=None, description="当前目标")
