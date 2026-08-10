"""AdaptivePolicy：规则式自适应教学决策（V1 baseline）。

输入：LearnerState + SelectedContext + TemporalState + Domain Context + Task Type。
输出：AdaptiveDecision（结构化 + reason_codes）。

策略组件拆分（避免 1000 行 if/else）：
- mastery_policy        ：掌握度 → 深度/难度/动作
- confidence_policy     ：置信度 → 保守程度
- prerequisite_policy   ：前置掌握度 → 是否先补前置
- misconception_policy  ：活跃误解 → 针对性动作
- preference_policy     ：偏好 → 交付模式/示例数（Pedagogical Need > Preference）
- temporal_policy       ：时间衰减 → 复习 or 新学

接口未来可扩展：rule-based → LLM-based → contextual bandit → RL。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.adaptive.schemas import (
    REASON_ACTIVE_MISCONCEPTION,
    REASON_HIGH_REVIEW_RISK,
    REASON_LOW_MASTERY_CONFIDENCE,
    REASON_LOW_PREREQUISITE_MASTERY,
    REASON_LOW_TARGET_MASTERY,
    REASON_LOW_UNDERSTANDING_ABILITY,
    REASON_NO_DATA,
    REASON_PREFERENCE_WORKED_EXAMPLE,
    REASON_REPEATED_REEXPLANATION,
    REASON_TARGET_MASTERED,
    AdaptiveDecision,
    SelectedLearnerContext,
    TaskType,
)
from edu_agent.adaptive.temporal_resolver import resolve
from edu_agent.domain.kc_graph import Course
from edu_agent.integrations.learner_state.schemas import (
    CourseLearnerState,
    KnowledgeItem,
)

MASTERED_THRESHOLD = 0.7
CONFIDENCE_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# 策略组件
# ---------------------------------------------------------------------------


def mastery_policy(mastery: float, reason_codes: List[str]) -> Dict[str, object]:
    """掌握度 → 深度/难度/基础动作。"""
    if mastery < 0.3:
        reason_codes.append(REASON_LOW_TARGET_MASTERY)
        return {
            "depth": "basic",
            "difficulty": "easy",
            "scaffold_level": "high",
            "pedagogical_actions": ["EXPLAIN", "WORKED_EXAMPLE"],
            "review_or_new": "new",
        }
    if mastery < MASTERED_THRESHOLD:
        return {
            "depth": "medium",
            "difficulty": "medium",
            "scaffold_level": "medium",
            "pedagogical_actions": ["EXPLAIN", "WORKED_EXAMPLE", "CHECK_UNDERSTANDING"],
            "review_or_new": "new",
        }
    reason_codes.append(REASON_TARGET_MASTERED)
    return {
        "depth": "concise",
        "difficulty": "hard",
        "scaffold_level": "low",
        "pedagogical_actions": ["SUMMARIZE", "DEEPEN", "SOCRATIC_QUESTION"],
        "review_or_new": "review",
    }


def confidence_policy(confidence: float, reason_codes: List[str]) -> Dict[str, object]:
    """置信度低 → 保守教学（不武断 mastered/weak），多检查。"""
    if confidence < CONFIDENCE_THRESHOLD:
        reason_codes.append(REASON_LOW_MASTERY_CONFIDENCE)
        return {
            "pedagogical_actions": ["EXPLAIN", "CHECK_UNDERSTANDING"],
            "scaffold_level": "medium",
        }
    return {}


def prerequisite_policy(
    target_kc: str,
    course: Course,
    knowledge_map: Dict[str, KnowledgeItem],
    reason_codes: List[str],
) -> Dict[str, object]:
    """前置未掌握 → REVIEW_PREREQUISITE（用传递前置链，如 多态→继承→封装）。"""
    missing: List[str] = []
    for prereq in course.all_prerequisites_transitive(target_kc):
        item = knowledge_map.get(prereq)
        if item is None or item.mastery < MASTERED_THRESHOLD:
            missing.append(prereq)
    if missing:
        reason_codes.append(REASON_LOW_PREREQUISITE_MASTERY)
        return {
            "review_prerequisite": True,
            "prerequisite_topics": missing,
            "pedagogical_actions": ["REVIEW_PREREQUISITE"] + ["EXPLAIN", "WORKED_EXAMPLE"],
            "content_order": missing + [target_kc],
        }
    return {}


def misconception_policy(
    misconceptions: List[dict],
    reason_codes: List[str],
) -> Dict[str, object]:
    """活跃误解 → 针对性动作（反例/概念对比）。"""
    active = [
        m for m in misconceptions
        if m.get("status", "active") == "active" and m.get("severity", 0) >= 0.5
    ]
    if active:
        reason_codes.append(REASON_ACTIVE_MISCONCEPTION)
        return {
            "pedagogical_actions": ["CONCEPT_COMPARISON", "COUNTEREXAMPLE"] + ["EXPLAIN"],
            "content_order": ["misconception_clarify"],
        }
    return {}


def preference_policy(
    preferences: dict,
    pedagogical_need: str,
    reason_codes: List[str],
) -> Dict[str, object]:
    """偏好只决定「交付形式」，不改变「教学需要」。

    Pedagogical Need > Task Suitability > User Preference。
    """
    preferred_mode = preferences.get("preferred_mode", "")
    mode_effectiveness = preferences.get("mode_effectiveness", {}) or {}

    # 教学需要是 worked example 时，偏好决定例子形式
    if pedagogical_need in ("EXPLAIN", "WORKED_EXAMPLE"):
        if preferred_mode in ("example_driven", "worked_example"):
            reason_codes.append(REASON_PREFERENCE_WORKED_EXAMPLE)
            return {"delivery_mode": "worked_example", "example_count": 2}
        if preferred_mode == "visual":
            return {"delivery_mode": "visual", "example_count": 1}
        if preferred_mode == "reading":
            return {"delivery_mode": "reading", "example_count": 1}

    # 用实测效果兜底：选效果最好的模式
    if mode_effectiveness:
        best_mode = max(
            mode_effectiveness.items(),
            key=lambda kv: kv[1].get("score", 0) if isinstance(kv[1], dict) else kv[1],
        )[0]
        return {"delivery_mode": best_mode, "example_count": 1}
    return {}


def temporal_policy(
    temporal: object,
    reason_codes: List[str],
) -> Dict[str, object]:
    """时间衰减 → review_or_new。"""
    state = temporal
    if getattr(state, "review_risk", "low") in ("high", "medium"):
        reason_codes.append(REASON_HIGH_REVIEW_RISK)
        return {
            "review_or_new": "review",
            "pedagogical_actions": ["SUMMARIZE", "CHECK_UNDERSTANDING"],
        }
    return {}


def ability_policy(
    abilities: Dict[str, float],
    reason_codes: List[str],
) -> Dict[str, object]:
    """理解能力低 → 简化 + 分步骤。"""
    understanding = abilities.get("understanding", 0.5)
    if understanding < 0.3:
        reason_codes.append(REASON_LOW_UNDERSTANDING_ABILITY)
        return {
            "pedagogical_actions": ["DECOMPOSE", "SIMPLIFY", "EXPLAIN"],
            "depth": "basic",
        }
    return {}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def make_decision(
    context: SelectedLearnerContext,
    course: Course,
    task_type: TaskType = "topic_tutor",
    session_re_explain_count: int = 0,
    delivery_mode_hint: str = "",
) -> AdaptiveDecision:
    """综合各策略组件生成 AdaptiveDecision。"""
    reasons: List[str] = []

    # 1) 目标 KC 状态
    knowledge_map: Dict[str, KnowledgeItem] = {}
    for item in context.knowledge_snapshot:
        if item.get("kc_id"):
            knowledge_map[item["kc_id"]] = KnowledgeItem(**item)
        elif item.get("name"):
            knowledge_map[item["name"]] = KnowledgeItem(kc_id=item["name"], **item)

    target_item = None
    if context.target_kc:
        target_item = knowledge_map.get(context.target_kc)
        if target_item is None:
            # 知识快照可能用名称而非 id
            for k, v in knowledge_map.items():
                if v.name == context.target_kc:
                    target_item = v
                    break

    target_mastery = target_item.mastery if target_item else 0.0
    target_confidence = target_item.confidence if target_item else 0.0

    # 2) 时间衰减
    temporal = resolve(target_item)
    context.temporal = temporal

    # 3) 逐组件决策（后写的组件在不覆盖已有 key 的前提下合并）
    decision = AdaptiveDecision(
        task_type=task_type,
        target_kc=context.target_kc,
        learner_state_version=context.learner_state_version,
        depth="medium",
        difficulty="medium",
        scaffold_level="medium",
        delivery_mode="explanation",
        example_count=1,
        pedagogical_actions=["EXPLAIN"],
        reason_codes=reasons,
    )

    def _merge(partial: Dict[str, object]) -> None:
        for key, value in partial.items():
            if key == "pedagogical_actions":
                existing = decision.pedagogical_actions
                for action in value:
                    if action not in existing:
                        existing.append(action)
            elif key == "content_order":
                decision.content_order = value
            elif key == "reason_codes":
                continue
            else:
                setattr(decision, key, value)

    _merge(mastery_policy(target_mastery, reasons))
    _merge(confidence_policy(target_confidence, reasons))
    _merge(ability_policy(context.abilities, reasons))
    _merge(temporal_policy(temporal, reasons))

    if context.target_kc:
        _merge(prerequisite_policy(context.target_kc, course, knowledge_map, reasons))
    _merge(misconception_policy(context.misconceptions, reasons))

    # 4) 偏好（Pedagogical Need 优先）
    pedagogical_need = decision.pedagogical_actions[0] if decision.pedagogical_actions else "EXPLAIN"
    if delivery_mode_hint:
        decision.delivery_mode = delivery_mode_hint  # type: ignore[assignment]
    else:
        _merge(preference_policy(context.preferences, pedagogical_need, reasons))

    # 5) 下一步推荐：可达前沿
    try:
        from edu_agent.domain.kc_graph import recommended_next

        mastery_map = {
            item["kc_id"]: item.get("mastery", 0.0)
            for item in context.knowledge_snapshot if item.get("kc_id")
        }
        next_kcs = recommended_next(course, mastery_map, goal_kcs=[context.target_kc] if context.target_kc else None)
        if next_kcs:
            decision.next_kc = next_kcs[0]
    except Exception:  # noqa: BLE001 - 推荐失败不影响主决策
        pass

    # 6) 会话信号：重复追问 → 降抽象、加示例
    if session_re_explain_count >= 2:
        reasons.append(REASON_REPEATED_REEXPLANATION)
        decision.scaffold_level = "high"
        decision.depth = "basic"
        if "SIMPLIFY" not in decision.pedagogical_actions:
            decision.pedagogical_actions.append("SIMPLIFY")
        if "WORKED_EXAMPLE" not in decision.pedagogical_actions:
            decision.pedagogical_actions.append("WORKED_EXAMPLE")
        decision.example_count = max(decision.example_count, 3)

    # 清理 reason_codes 去重
    decision.reason_codes = list(dict.fromkeys(reasons))

    # 无目标数据时标记
    if target_item is None and not context.knowledge_snapshot:
        reasons.append(REASON_NO_DATA)

    # content_order 默认
    if not decision.content_order:
        order = []
        if decision.review_prerequisite:
            order = decision.prerequisite_topics + [context.target_kc] if context.target_kc else decision.prerequisite_topics
        elif context.target_kc:
            order = [context.target_kc]
        decision.content_order = order

    return decision
