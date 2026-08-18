"""Prerequisite-aware heuristic 自适应策略。

输入：Course（KC DAG）+ learner mastery/confidence/misconceptions。
输出：每个 KC 的 locked / recommended / reason_codes，以及全局 recommended_path。

设计原则：
- 确定性（无随机），可单测，可解释。
- UNKNOWN != 0：前置 UNKNOWN 视为"尚未证明满足" → 锁定，而非 mastery=0。
- 不实现强化学习 / 复杂图搜索。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.adaptive.reason_codes import ReasonCode
from edu_agent.adaptive.thresholds import (
    MASTERED_THRESHOLD,
    WEAK_THRESHOLD,
    classify_status,
)
from edu_agent.domain.learning.course import Course


class HeuristicAdaptivePolicy:
    """基于前置依赖与掌握度的启发式策略。"""

    def __init__(
        self,
        course: Course,
        goal_kcs: Optional[List[str]] = None,
        target_kcs: Optional[List[str]] = None,
        mastered_threshold: float = MASTERED_THRESHOLD,
        weak_threshold: float = WEAK_THRESHOLD,
    ) -> None:
        self.course = course
        self.goal_kcs = set(goal_kcs or [])
        # target_kcs：真正的学习目标 KC（通常是末端节点）。
        # 缺省 = 没有任何后继的叶子 KC。
        if target_kcs is not None:
            self.target_kcs = set(target_kcs)
        else:
            self.target_kcs = {
                c.kc_id for c in course.components
                if not course.dependents(c.kc_id)
            }
        self._goal_rel_memo: Dict[str, bool] = {}
        self.mastered_threshold = mastered_threshold
        self.weak_threshold = weak_threshold

    # -- 基础状态 ----------------------------------------------------------
    def status_of(self, kc_id: str, mastery: Optional[float]) -> str:
        return classify_status(mastery)

    def is_mastered(self, mastery: Optional[float]) -> bool:
        return mastery is not None and mastery >= self.mastered_threshold

    # -- 锁定判定 ----------------------------------------------------------
    def prereq_status(self, kc_id: str, mastery_map: Dict[str, Optional[float]]) -> List[dict]:
        """返回 kc_id 的直接前置状态。"""
        out: List[dict] = []
        for p in self.course.prerequisites(kc_id):
            pv = mastery_map.get(p)
            if pv is None:
                state = "unknown"
            elif pv < self.mastered_threshold:
                state = "weak"
            else:
                state = "mastered"
            out.append({"kc_id": p, "mastery": pv, "state": state})
        return out

    def is_locked(self, kc_id: str, mastery_map: Dict[str, Optional[float]]) -> bool:
        """存在尚未达到 threshold 的前置（含 UNKNOWN）→ 锁定。

        已 mastered 的 KC 视为已解锁（不再参与锁定判定）。
        """
        if self.is_mastered(mastery_map.get(kc_id)):
            return False
        for p in self.course.prerequisites(kc_id):
            pv = mastery_map.get(p)
            if pv is None or pv < self.mastered_threshold:
                return True
        return False

    # -- 目标相关性（递归，忽略已 mastered 的后继）--------------------------
    def is_goal_relevant(self, kc_id: str, mastery_map: Dict[str, Optional[float]]) -> bool:
        """一个 KC 对"未掌握的学习目标"仍有贡献 → 相关。

        规则：
        - 自身已 mastered → 不再相关（无需继续学）。
        - 自身是 target_kcs 之一且未掌握 → 相关。
        - 存在未 mastered 的后继 d，且 d 自身仍相关 → 相关。
        已 mastered 的后继不会向上传播相关性（这正是排除 token_context 之类冗余上游 KC 的关键）。
        """
        if kc_id in self._goal_rel_memo:
            return self._goal_rel_memo[kc_id]
        if self.is_mastered(mastery_map.get(kc_id)):
            self._goal_rel_memo[kc_id] = False
            return False
        if kc_id in self.target_kcs:
            self._goal_rel_memo[kc_id] = True
            return True
        for d in self.course.dependents(kc_id):
            if self.is_goal_relevant(d, mastery_map):
                self._goal_rel_memo[kc_id] = True
                return True
        self._goal_rel_memo[kc_id] = False
        return False

    # -- 单 KC 评估 --------------------------------------------------------
    def evaluate_kc(
        self,
        kc_id: str,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
    ) -> dict:
        misconception_map = misconception_map or {}
        recent_error_map = recent_error_map or {}

        mastery = mastery_map.get(kc_id)
        status = self.status_of(kc_id, mastery)
        locked = self.is_locked(kc_id, mastery_map)
        prereqs = self.prereq_status(kc_id, mastery_map)

        misconceptions = misconception_map.get(kc_id, [])
        recent_error = bool(recent_error_map.get(kc_id, False))

        reason_codes: List[str] = []

        if status == "unknown":
            reason_codes.append(ReasonCode.UNKNOWN_STATE.value)
        elif status == "weak":
            reason_codes.append(ReasonCode.LOW_MASTERY.value)
        elif status == "mastered":
            reason_codes.append(ReasonCode.MASTERY_THRESHOLD_REACHED.value)

        if misconceptions:
            reason_codes.append(ReasonCode.MISCONCEPTION_DETECTED.value)
        if recent_error:
            reason_codes.append(ReasonCode.RECENT_ERROR.value)

        # 目标相关性（递归：忽略已 mastered 的后继，避免推荐冗余上游 KC）
        goal_relevant = self.is_goal_relevant(kc_id, mastery_map)
        if goal_relevant:
            reason_codes.append(ReasonCode.GOAL_RELEVANT.value)
            if kc_id in self.goal_kcs or any(
                d in self.goal_kcs for d in self.course.all_prerequisites_transitive(kc_id)
            ):
                reason_codes.append(ReasonCode.PREREQUISITE_FOR_GOAL.value)

        if locked:
            reason_codes.append(ReasonCode.PREREQUISITE_NOT_MET.value)
        else:
            if prereqs:
                reason_codes.append(ReasonCode.PREREQUISITE_SATISFIED.value)

        # recommended：未掌握 + 未锁定 + 与目标相关
        recommended = (
            not self.is_mastered(mastery)
            and not locked
            and goal_relevant
        )
        if recommended:
            reason_codes.append(ReasonCode.NEXT_IN_PLAN.value)

        return {
            "kc_id": kc_id,
            "mastery": mastery,
            "status": status,
            "locked": locked,
            "recommended": recommended,
            "prerequisites": prereqs,
            "misconceptions": misconceptions,
            "recent_error": recent_error,
            "goal_relevant": goal_relevant,
            "reason_codes": reason_codes,
        }

    # -- 全局推荐路径 ------------------------------------------------------
    def recommended_path(
        self,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
        current_kc: Optional[str] = None,
    ) -> List[str]:
        """确定性推荐路径：候选 KC 按优先级排序。

        priority = goal_relevance + mastery_weakness + prerequisite_readiness
                   + recent_error_weight + current_plan_weight
        """
        results = [
            self.evaluate_kc(kc_id, mastery_map, misconception_map, recent_error_map)
            for kc_id in (c.kc_id for c in self.course.components)
        ]
        candidates = [r for r in results if r["recommended"]]
        if not candidates:
            # 全部 mastered 或锁定 → 给出未掌握但锁定的（等待解锁）或空
            return []

        def priority(r: dict) -> tuple:
            goal_rel = 1 if r["goal_relevant"] else 0
            # 掌握度越弱越优先（unknown 视作最弱，给 0.0 以优先于 weak）
            mastery = r["mastery"]
            weakness = (0.0 if mastery is None else mastery)
            # 前置准备度：前置越接近满足越优先
            prereqs = r["prerequisites"]
            if not prereqs:
                readiness = 1.0
            else:
                readiness = sum(
                    1.0 if p["state"] == "mastered" else (0.5 if p["state"] == "weak" else 0.0)
                    for p in prereqs
                ) / len(prereqs)
            recent_err = 1 if r["recent_error"] else 0
            current_plan = 1 if (current_kc and r["kc_id"] == current_kc) else 0
            # 综合分数（越高越优先）；用负 weakness 让更弱的排前
            score = (
                goal_rel * 3.0
                + (1.0 - weakness) * 2.0
                + readiness * 1.0
                + recent_err * 0.5
                + current_plan * 0.5
            )
            # 同分时稳定排序：kc_id
            return (-score, r["kc_id"])

        ordered = sorted(candidates, key=priority)
        return [r["kc_id"] for r in ordered]

    def current_recommended_kc(self, path: List[str]) -> Optional[str]:
        return path[0] if path else None

    # -- 推荐候选（current + candidates）-----------------------------------
    def recommended_candidates(
        self,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
        max_candidates: int = 3,
    ) -> List[str]:
        """返回可学的推荐候选（排除当前推荐后的 1~max_candidates 个）。"""
        path = self.recommended_path(mastery_map, misconception_map, recent_error_map)
        if not path:
            return []
        return path[1:1 + max_candidates]

    # -- active_path：真实 DAG 路径（相邻节点必须有 prerequisite edge）------
    def active_path(
        self,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
        start_kc: Optional[str] = None,
        max_len: int = 6,
    ) -> List[str]:
        """沿 prerequisite 依赖方向（当前 → 后继）走出真实路径。

        保证：path 中任意相邻 (p, n) 都满足 ``n`` 是 ``p`` 的后继（即存在
        p→n 的 prerequisite edge）。起点取当前推荐；若当前推荐已被掌握，
        从首个未掌握且未锁定的可学节点开始。
        """
        path_ordered = self.recommended_path(mastery_map, misconception_map, recent_error_map)
        cur = start_kc or (path_ordered[0] if path_ordered else None)
        if cur is None:
            return []

        result: List[str] = [cur]
        for _ in range(max_len - 1):
            # 沿后继方向：选择未掌握、未锁定的后继；若有多个，优先推荐顺序中靠前的。
            dependents = [d for d in self.course.dependents(cur)]
            if not dependents:
                break
            # 过滤出可继续学习的后继（未掌握 + 未锁定）
            candidates = [
                d for d in dependents
                if not self.is_mastered(mastery_map.get(d))
                and not self.is_locked(d, mastery_map)
            ]
            if not candidates:
                break
            # 与推荐顺序对齐（推荐顺序里越靠前的后继越优先）
            rank = {k: i for i, k in enumerate(path_ordered)}
            candidates.sort(key=lambda d: rank.get(d, len(path_ordered)))
            nxt = candidates[0]
            result.append(nxt)
            cur = nxt
        return result
