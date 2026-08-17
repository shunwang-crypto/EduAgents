"""Tutoring 工作流的三核心 Agent：Planner / Tutor / Diagnoser。

设计约束：
- runtime 教学 Agent 只有这三个角色；KCGraph / LearnerModelService /
  KnowledgeUpdater / AdaptivePolicy 不是 Agent。
- Planner 不负责最终教学文本；Tutor 不直接写 mastery；Diagnoser 不直接更新库。
- 所有 LLM 调用都必须有确定性回退（离线 / 无 key 时系统仍可用）。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from edu_agent.adaptive.policies.heuristic import HeuristicAdaptivePolicy
from edu_agent.adaptive.reason_codes import ReasonCode
from edu_agent.adaptive.thresholds import MASTERED_THRESHOLD
from edu_agent.core.llm import get_llm
from edu_agent.domain.learning.course import Course
from edu_agent.workflows.tutoring.schemas import (
    Diagnosis,
    PlannerDecision,
    TeachingAction,
    TutorResponse,
)
from edu_agent.workflows.tutoring.strategy import decide_action, tune_difficulty

logger = logging.getLogger("edu_agent.tutoring.agents")


def _looks_like_answer(msg: str) -> bool:
    """粗略判断回答是否有实质内容（避免空话/重复问题被当作有效证据）。"""
    if not msg:
        return False
    # 极短 / 只剩标点 / 单纯重复问题词汇 → 不视为有效作答
    stripped = re.sub(r"[，。！？、；：,.!?;: ]", "", msg)
    if len(stripped) < 2:
        return False
    return True


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """决定：下一步学哪个 KC + 这一轮用什么 Teaching Action。"""

    def __init__(self, course: Course, goal_kcs: Optional[List[str]] = None) -> None:
        self.course = course
        self.goal_kcs = goal_kcs or []
        self.policy = HeuristicAdaptivePolicy(course, goal_kcs=self.goal_kcs)

    def plan(
        self,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
        current_kc: Optional[str] = None,
        consecutive_errors: int = 0,
        consecutive_successes: int = 0,
    ) -> PlannerDecision:
        misconception_map = misconception_map or {}
        recent_error_map = recent_error_map or {}

        path = self.policy.recommended_path(
            mastery_map,
            misconception_map,
            recent_error_map,
            current_kc=current_kc,
        )
        selected_kc = current_kc if current_kc and current_kc in (
            c.kc_id for c in self.course.components
        ) else (path[0] if path else None)

        if selected_kc is None:
            # 没有候选（全部 mastered / 锁定）→ 选目标 KC 中未掌握的
            for g in self.goal_kcs:
                if not self.policy.is_mastered(mastery_map.get(g)):
                    selected_kc = g
                    break
        if selected_kc is None:
            # 兜底：课程第一个 KC
            selected_kc = self.course.components[0].kc_id

        mastery = mastery_map.get(selected_kc)
        teaching_action = decide_action(
            mastery,
            misconception_map.get(selected_kc, []),
            consecutive_errors,
            consecutive_successes,
        )
        difficulty = tune_difficulty(
            1, consecutive_errors, consecutive_successes
        )

        # 汇总该 KC 的 reason codes
        eval_res = self.policy.evaluate_kc(
            selected_kc, mastery_map, misconception_map, recent_error_map
        )
        reason_codes = list(eval_res["reason_codes"])

        # 生成可解释"为什么"（非 CoT）
        why = self._explain(selected_kc, eval_res, teaching_action)

        return PlannerDecision(
            selected_kc=selected_kc,
            teaching_action=teaching_action,
            difficulty=difficulty,
            reason_codes=reason_codes,
            rationale=why,
        )

    def _explain(self, kc_id: str, eval_res: dict, action: TeachingAction) -> str:
        kc = self.course.kc_by_id(kc_id)
        name = kc.title if kc else kc_id
        parts: List[str] = [f"推荐学习《{name}》。"]
        if eval_res["status"] == "unknown":
            parts.append("当前尚未评估（UNKNOWN）。")
        elif eval_res["status"] == "weak":
            parts.append(f"当前掌握度偏低（{eval_res['mastery']:.0%}）。")
        elif eval_res["status"] == "learning":
            parts.append(f"当前正在学习中（{eval_res['mastery']:.0%}）。")
        if eval_res["goal_relevant"]:
            parts.append("该节点与学习目标直接相关。")
        if eval_res["recent_error"]:
            parts.append("最近一次作答有误。")
        if eval_res["misconceptions"]:
            parts.append(f"存在误区：{', '.join(eval_res['misconceptions'])}。")
        parts.append(f"本轮教学动作：{action.value}。")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Diagnoser
# ---------------------------------------------------------------------------


class Diagnoser:
    """对用户回复做结构化诊断；输出 Diagnosis，不直接写库。"""

    def __init__(self, course: Course) -> None:
        self.course = course

    def diagnose(
        self,
        kc_id: str,
        learner_message: str,
        expected_answer_hint: Optional[str] = None,
        teaching_action: Optional[str] = None,
    ) -> Diagnosis:
        kc = self.course.kc_by_id(kc_id)
        kc_title = kc.title if kc else kc_id

        # 确定性回退：基于规则的关键词判断，保证离线可用。
        # P1-6：规则必须参考原问题/评估提示，且不能靠“向量/相似”这类万能关键词判正确。
        fallback = self._rule_based_diagnosis(
            kc_id, kc_title, learner_message,
            expected_answer_hint=expected_answer_hint,
            teaching_action=teaching_action,
        )

        try:
            llm = get_llm(temperature=0.0)
            from edu_agent.core.agent_runner import invoke_structured_output

            prompt = (
                "你是一个严谨的诊断器。给定一个知识组件、学习目标相关提示、本轮教学动作、"
                "本轮教学问题（评估提示），以及学习者的回答，判断其是否正确、是否存在误区、"
                "证据强度如何。\n"
                "不要输出思维链，只输出结构化判断。\n"
                "correctness 取值：correct / partial / incorrect。\n"
                "evidence_strength 取值：weak / medium / strong。无法合理判断时用 weak。\n"
                "misconceptions 是简短的误区标识列表（英文 snake_case），没有则为空列表。"
            )
            values = {
                "kc_id": kc_id,
                "kc_title": kc_title,
                "teaching_action": teaching_action or "",
                "expected_hint": expected_answer_hint or "（未提供标准答案提示）",
                "learner_message": learner_message or "（空回答）",
            }
            result = invoke_structured_output(prompt, Diagnosis, values, llm)
            # 合并：若 LLM 未给 misconceptions 但规则发现，则保留规则结果
            if not result.misconceptions and fallback.misconceptions:
                result.misconceptions = fallback.misconceptions
            return result
        except Exception as exc:  # noqa: BLE001 - 任何 LLM 失败都用确定性回退
            logger.warning("Diagnoser LLM 不可用，使用规则回退：%s", exc)
            return fallback

    def _rule_based_diagnosis(
        self,
        kc_id: str,
        kc_title: str,
        message: str,
        expected_answer_hint: Optional[str] = None,
        teaching_action: Optional[str] = None,
    ) -> Diagnosis:
        """确定性回退诊断。

        P1-6：禁止“只要提到向量/相似就判正确”的万能规则。回退只在本轮问题确实是
        关于某个 KC 的语义/相似度判断时才启用对应关键词；否则无法合理判断 →
        返回 ``evidence_strength=weak``（updater 不会据此快速提高 mastery）。
        """
        msg = (message or "").strip().lower()
        hint = (expected_answer_hint or "").lower()
        misconceptions: List[str] = []
        correctness = "incorrect"
        strength = "weak"
        confidence = 0.4

        # 仅当本轮确实在考查 embedding 的“语义相似/距离”概念时，才启用对应关键词规则。
        # 对 embedding KC（或其问题提到 embedding）启用；对任意其他 KC 绝不套用
        # “提到向量/相似就判正确”的万能规则（P1-6）。
        is_semantic_question = (kc_id == "embedding") or ("embedding" in hint)

        if is_semantic_question and msg:
            # 误区：把语义相似误当字面相似
            if "字面" in msg or "lexical" in msg or "字符" in msg or "词序" in msg:
                misconceptions.append("embedding_similarity_equals_lexical_similarity")
            if any(w in msg for w in ["语义", "semantic", "语义相似"]):
                correctness = "partial"
                strength = "medium"
            if any(w in msg for w in ["向量", "vector", "距离", "distance", "余弦", "cosine"]):
                correctness = "correct"
                strength = "medium"
            confidence = 0.6
        elif msg and not _looks_like_answer(msg):
            # 有回答但无法套用任何 KC 规则 → 弱证据，不做强判断。
            correctness = "partial"
            strength = "weak"

        return Diagnosis(
            kc_id=kc_id,
            correctness=correctness,
            confidence=confidence,
            evidence_strength=strength,
            misconceptions=misconceptions,
            hint_level=0,
            difficulty=1,
        )


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------


class Tutor:
    """根据 Planner 决策生成面向用户的教学消息。不直接修改 mastery。"""

    def __init__(self, course: Course) -> None:
        self.course = course

    def teach(
        self,
        decision: PlannerDecision,
        learner_message: Optional[str] = None,
        misconception_list: Optional[List[str]] = None,
    ) -> TutorResponse:
        kc_id = decision.selected_kc
        kc = self.course.kc_by_id(kc_id)
        kc_title = kc.title if kc else kc_id
        action = decision.teaching_action

        fallback_msg = self._fallback_message(kc_id, kc_title, action, misconception_list)
        message = fallback_msg

        try:
            llm = get_llm(temperature=0.6)
            from edu_agent.core.agent_runner import invoke_structured_output
            from pydantic import BaseModel, Field

            class _TutorOut(BaseModel):
                message: str = Field(description="面向学习者的教学消息")

            prompt = (
                "你是耐心的智能导师。给定知识组件、已确定的教学动作（不可更改）、"
                "以及学习者上一轮回复，生成一段面向学习者的教学消息。\n"
                "约束：\n"
                "1. 严格遵循给定的 teaching_action，不要擅自改为长篇讲解（除非动作是 EXPLAIN）。\n"
                "2. 如果动作是 ASSESS / PROBE，只提出问题并等待回答，不要立即给答案。\n"
                "3. 不要输出任何内部思维链。\n"
            )
            values = {
                "kc_title": kc_title,
                "kc_description": kc.description if kc else "",
                "teaching_action": action.value,
                "learner_message": learner_message or "（新的一轮 / 尚未回答）",
                "misconceptions": ", ".join(misconception_list or []),
            }
            out = invoke_structured_output(prompt, _TutorOut, values, llm)
            if out and out.message:
                message = out.message
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tutor LLM 不可用，使用确定性回退问题：%s", exc)
            message = fallback_msg

        return TutorResponse(
            kc_id=kc_id,
            teaching_action=action,
            message=message,
            reason_codes=decision.reason_codes,
            explanation=decision.rationale,
            next_recommended_kc=kc_id,
        )

    def _fallback_message(
        self,
        kc_id: str,
        kc_title: str,
        action: TeachingAction,
        misconception_list: Optional[List[str]] = None,
    ) -> str:
        if action == TeachingAction.ASSESS:
            if kc_id == "embedding":
                return (
                    "假设有三句话：\n"
                    "A. 我正在学习人工智能\n"
                    "B. 我喜欢机器学习\n"
                    "C. 今天下雨了\n\n"
                    "如果将它们转换为 embedding，你认为哪两个向量通常距离更近？为什么？"
                )
            return f"我们来检测一下你对《{kc_title}》的理解：请用你自己的话解释它的核心思想。"
        if action == TeachingAction.PROBE:
            return f"关于《{kc_title}》，你刚才说的“接近”是指文字形式上的接近，还是语义上的接近？"
        if action == TeachingAction.COMPARE:
            return (
                f"注意一个常见误区：语义相似 ≠ 字面/词序相似。"
                f"我们用一个反例来比较《{kc_title}》："
                "“苹果手机”和“苹果水果”字面都有“苹果”，但它们的 embedding 会很接近吗？"
            )
        if action == TeachingAction.EXPLAIN:
            return f"下面系统讲解《{kc_title}》的核心概念与原理。"
        if action == TeachingAction.HINT:
            return f"给你一个提示：可以从《{kc_title}》最关键的一个属性入手思考。"
        if action == TeachingAction.EXAMPLE:
            return f"举一个《{kc_title}》的简单例子来帮助理解。"
        if action == TeachingAction.PRACTICE:
            return f"现在做一道《{kc_title}》的练习来巩固。"
        if action == TeachingAction.CHALLENGE:
            return f"挑战一下：在更复杂场景下应用《{kc_title}》。"
        if action == TeachingAction.APPLICATION:
            return f"尝试把《{kc_title}》应用到你自己的项目中。"
        return f"我们继续学习《{kc_title}》。"
