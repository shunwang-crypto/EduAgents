"""自适应引擎基础模型：SelectedLearnerContext / AdaptiveDecision。

原则：
- 上下文选择器负责「只挑相关状态」，禁止把完整 LearnerState 塞给 LLM。
- 策略输出结构化决策 + reason_codes（可解释），Prompt Builder 只做转换。
- 决策基于哪个 LearnerState 版本必须记录（learner_state_version）。
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 固定 Pedagogical Action 集（V1，不含练习系统动作）
# ---------------------------------------------------------------------------

PED_ACTIONS: List[str] = [
    "EXPLAIN",
    "WORKED_EXAMPLE",
    "PARTIAL_EXAMPLE",
    "HINT",
    "ANALOGY",
    "COUNTEREXAMPLE",
    "REVIEW_PREREQUISITE",
    "SUMMARIZE",
    "CONCEPT_COMPARISON",
    "DECOMPOSE",
    "SIMPLIFY",
    "DEEPEN",
    "CHECK_UNDERSTANDING",
    "SOCRATIC_QUESTION",
]

# 禁止出现的练习系统动作（防御性常量，供测试断言）
FORBIDDEN_ACTIONS = [
    "PRACTICE", "GENERATE_QUIZ", "EXERCISE", "TEST", "CHALLENGE_QUESTION",
]

# ---------------------------------------------------------------------------
# Reason Codes
# ---------------------------------------------------------------------------

REASON_LOW_TARGET_MASTERY = "LOW_TARGET_MASTERY"
REASON_LOW_PREREQUISITE_MASTERY = "LOW_PREREQUISITE_MASTERY"
REASON_LOW_MASTERY_CONFIDENCE = "LOW_MASTERY_CONFIDENCE"
REASON_ACTIVE_MISCONCEPTION = "ACTIVE_MISCONCEPTION"
REASON_HIGH_REVIEW_RISK = "HIGH_REVIEW_RISK"
REASON_PREFERENCE_WORKED_EXAMPLE = "PREFERENCE_WORKED_EXAMPLE"
REASON_LOW_UNDERSTANDING_ABILITY = "LOW_UNDERSTANDING_ABILITY"
REASON_REPEATED_REEXPLANATION = "REPEATED_REEXPLANATION"
REASON_TARGET_MASTERED = "TARGET_MASTERED"
REASON_NO_DATA = "NO_DATA"

TaskType = Literal["study_plan", "topic_tutor", "adaptive_qa", "plan_chat"]

Depth = Literal["basic", "medium", "deep", "concise"]
ScaffoldLevel = Literal["high", "medium", "low"]
DeliveryMode = Literal["explanation", "worked_example", "analogy", "visual", "reading", "code"]


class TemporalState(BaseModel):
    """Temporal Resolver 的输出。"""

    raw_mastery: float = Field(default=0.0)
    recency_days: float = Field(default=0.0)
    review_risk: Literal["low", "medium", "high"] = Field(default="low")
    effective_state: Literal["mastered", "learning", "weak", "needs_refresh", "unknown"] = Field(
        default="unknown"
    )
    source: str = Field(default="rule")


class SelectedLearnerContext(BaseModel):
    """AdaptiveContextSelector 的输出：只含当前任务相关的状态子集。"""

    task_type: TaskType = Field(default="topic_tutor")
    user_id: str = Field(default="")
    course_id: str = Field(default="")
    goal_id: str = Field(default="")
    goal_name: str = Field(default="")
    goal_target: str = Field(default="")
    goal_progress: float = Field(default=0.0)

    # 目标 KC 及其相关状态
    target_kc: Optional[str] = Field(default=None, description="目标 KC ID")
    target_kc_name: str = Field(default="")
    knowledge_snapshot: List[dict] = Field(
        default_factory=list, description="仅目标 KC + 其前置 KC 的掌握度快照"
    )
    prerequisites: List[str] = Field(default_factory=list, description="目标 KC 的前置（未掌握的在 policy 中判定）")
    prerequisite_knowledge: List[dict] = Field(default_factory=list, description="前置 KC 的掌握度")
    misconceptions: List[dict] = Field(default_factory=list, description="目标 KC 相关误解")
    abilities: Dict[str, float] = Field(default_factory=dict, description="相关能力分数")
    preferences: dict = Field(default_factory=dict, description="偏好快照")
    behavior: dict = Field(default_factory=dict, description="近期行为快照")
    temporal: TemporalState = Field(default_factory=TemporalState, description="时间衰减状态")
    freshness: str = Field(default="fresh", description="fresh/stale/mock/missing")
    learner_state_version: Optional[int] = Field(default=None, description="本次决策基于的画像版本")

    def to_prompt_snippet(self) -> str:
        """转成注入 LLM 的简短上下文（只含必要状态）。"""
        lines = [
            f"课程：{self.course_id}｜目标：{self.goal_name or self.goal_id or '未指定'}",
            f"状态新鲜度：{self.freshness}（画像版本 v{self.learner_state_version or '-'}）",
        ]
        if self.target_kc:
            lines.append(f"目标知识点：{self.target_kc_name or self.target_kc}")
        if self.knowledge_snapshot:
            parts = [
                f"{item.get('name') or item.get('kc_id')}(m={item.get('mastery', 0)},c={item.get('confidence', 0)})"
                for item in self.knowledge_snapshot[:6]
            ]
            lines.append("掌握度：\n- " + "\n- ".join(parts))
        if self.misconceptions:
            lines.append(
                "已知误解："
                + "; ".join(f"{m.get('description', '')}" for m in self.misconceptions[:3])
            )
        if self.temporal.effective_state != "unknown":
            lines.append(
                f"时间衰减：raw={self.temporal.raw_mastery:.2f}, "
                f"距上次证据 {self.temporal.recency_days:.0f} 天, "
                f"复习风险={self.temporal.review_risk}, 有效状态={self.temporal.effective_state}"
            )
        if self.abilities:
            top = sorted(self.abilities.items(), key=lambda kv: -kv[1])[:3]
            lines.append("能力维度：" + ", ".join(f"{k}={v:.2f}" for k, v in top))
        return "\n".join(lines)


class AdaptiveDecision(BaseModel):
    """Adaptive Policy 的结构化输出。"""

    task_type: TaskType = Field(default="topic_tutor")
    target_kc: Optional[str] = Field(default=None)
    next_kc: Optional[str] = Field(default=None, description="下一步建议学习的 KC")
    depth: Depth = Field(default="medium")
    difficulty: str = Field(default="medium")
    review_prerequisite: bool = Field(default=False)
    prerequisite_topics: List[str] = Field(default_factory=list)
    pedagogical_actions: List[str] = Field(default_factory=list)
    scaffold_level: ScaffoldLevel = Field(default="medium")
    delivery_mode: DeliveryMode = Field(default="explanation")
    example_count: int = Field(default=1)
    content_order: List[str] = Field(default_factory=list)
    resource_level: str = Field(default="standard")
    review_or_new: Literal["review", "new"] = Field(default="new")
    reason_codes: List[str] = Field(default_factory=list)
    learner_state_version: Optional[int] = Field(default=None)
    session_state_summary: str = Field(default="")

    def explain(self) -> str:
        """把决策转成人话（用于前端展示 Adaptive Decision Trace）。"""
        lines = [f"目标：{self.target_kc or '未指定'}｜深度：{self.depth}｜难度：{self.difficulty}"]
        if self.review_prerequisite:
            lines.append(f"需要先补前置：{'、'.join(self.prerequisite_topics) or '无'}")
        lines.append("教学动作：" + " → ".join(self.pedagogical_actions) or "无")
        lines.append(f"支架：{self.scaffold_level}｜模式：{self.delivery_mode}｜示例数：{self.example_count}")
        lines.append(f"原因码：{', '.join(self.reason_codes) or '无'}")
        return "\n".join(lines)
