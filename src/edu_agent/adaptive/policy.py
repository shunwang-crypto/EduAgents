"""AdaptivePolicy 主入口：组装各策略组件生成 AdaptiveDecision。

策略组件在 `adaptive/policies/` 独立拆分（可单独测试）。
reason_codes：所有组件只 append 到统一 reasons 列表，
最后一次性去重写入 decision.reason_codes（避免中途复制丢失）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.adaptive.policies import (
    ability_policy,
    confidence_policy,
    mastery_policy,
    misconception_policy,
    preference_policy,
    prerequisite_policy,
    temporal_policy,
)
from edu_agent.adaptive.schemas import (
    REASON_NO_DATA,
    REASON_REPEATED_REEXPLANATION,
    AdaptiveDecision,
    SelectedLearnerContext,
    TaskType,
)
from edu_agent.adaptive.temporal_resolver import resolve
from edu_agent.domain.learning.kc_graph import Course
from edu_agent.learner_model.schemas import KnowledgeItem


def make_decision(
    context: SelectedLearnerContext,
    course: Course,
    task_type: TaskType = "topic_tutor",
    session_re_explain_count: int = 0,
    delivery_mode_hint: str = "",
) -> AdaptiveDecision:
    """综合各策略组件生成 AdaptiveDecision。"""
    reasons: List[str] = []

    # 1) 目标 KC 状态（mastery 可能是 None = UNKNOWN）
    knowledge_map: Dict[str, KnowledgeItem] = {}
    for item in context.knowledge_snapshot:
        if item.get("kc_id"):
            knowledge_map[item["kc_id"]] = KnowledgeItem(**item)
        elif item.get("name"):
            knowledge_map[item["name"]] = KnowledgeItem(kc_id=item["name"], **item)

    target_item: Optional[KnowledgeItem] = None
    if context.target_kc:
        target_item = knowledge_map.get(context.target_kc)
        if target_item is None:
            for k, v in knowledge_map.items():
                if v.name == context.target_kc:
                    target_item = v
                    break

    target_mastery = target_item.mastery if target_item else None  # None=UNKNOWN
    target_confidence = target_item.confidence if target_item else None

    # 2) 时间衰减
    temporal = resolve(target_item)
    context.temporal = temporal

    # 3) 逐组件决策（后写组件不覆盖已有 key 的前提下合并）
    decision = AdaptiveDecision(
        task_type=task_type,
        target_kc=context.target_kc,
        learner_state_version=context.learner_state_version,
        global_state_version=context.global_state_version,
        depth="medium",
        difficulty="medium",
        scaffold_level="medium",
        delivery_mode="explanation",
        example_count=1,
        pedagogical_actions=["EXPLAIN"],
        reason_codes=[],
    )

    def _merge(partial: Dict[str, object]) -> None:
        for key, value in partial.items():
            if key == "pedagogical_actions":
                for action in value:
                    if action not in decision.pedagogical_actions:
                        decision.pedagogical_actions.append(action)
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

    # 4) 偏好（Pedagogical Need 优先；前置缺口/误解/困惑不能被偏好覆盖）
    pedagogical_need = decision.pedagogical_actions[0] if decision.pedagogical_actions else "EXPLAIN"
    if delivery_mode_hint:
        decision.delivery_mode = delivery_mode_hint  # type: ignore[assignment]
    elif not decision.review_prerequisite and not context.misconceptions:
        _merge(preference_policy(context.preferences, pedagogical_need, reasons))

    # 5) 下一步推荐：可达前沿（KST-lite；UNKNOWN 排序靠后但优先于无关）
    try:
        from edu_agent.domain.learning.kc_graph import recommended_next

        mastery_map = {
            item["kc_id"]: item.get("mastery")
            for item in context.knowledge_snapshot if item.get("kc_id")
        }
        next_kcs = recommended_next(
            course, mastery_map,
            goal_kcs=[context.target_kc] if context.target_kc else None,
        )
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

    # 7) 无目标数据标记
    if target_item is None and not context.knowledge_snapshot:
        reasons.append(REASON_NO_DATA)

    # 8) 最后一次统一收集 reason_codes（去重保序）
    decision.reason_codes = list(dict.fromkeys(reasons))

    # content_order 默认
    if not decision.content_order:
        order: List[str] = []
        if decision.review_prerequisite:
            order = (decision.prerequisite_topics or []) + ([context.target_kc] if context.target_kc else [])
        elif context.target_kc:
            order = [context.target_kc]
        decision.content_order = order

    return decision
