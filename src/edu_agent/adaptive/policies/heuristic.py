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
        plan_order: Optional[Dict[str, int]] = None,
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
        # StudyPlan.seq 排序：kc_id → seq。同分时优先按计划顺序，
        # 绝不由 hash 类 canonical kc_id 决定学习顺序（§22）。
        self.plan_order = plan_order or {}
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
            # PREREQUISITE_FOR_GOAL 方向：kc 必须是某个 target 的传递前置
            # （kc ∈ transitive_prerequisites(target)），即 target ∈ kc 的传递后继。
            # target 自身不算（它是目标，不是"达成目标的前置"）。
            if any(
                t in self.course.all_dependents_transitive(kc_id) for t in self.target_kcs
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
            # 同分时优先按 StudyPlan.seq（越小越先），再按拓扑深度，
            # kc_id 仅作为最终确定性 fallback（§22：不由 hash 决定顺序）。
            seq = self.plan_order.get(r["kc_id"], 10**9)
            return (-score, seq, r["kc_id"])

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

    # -- active_subgraph：goal prerequisite closure --------------------------
    def active_subgraph(self) -> tuple[set[str], set[tuple[str, str]]]:
        """当前目标仍相关的知识 DAG 子图（§20）。

        计算：targets + targets 的所有传递前置（goal prerequisite closure）。
        mastered 节点仍保留（已完成上下文）；unknown/weak/learning 属于剩余学习工作；
        未来 locked 节点也必须出现在子图中（locked 只代表“现在不能作推荐入口”）。
        """
        keep: set[str] = set()
        stack = list(self.target_kcs)
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            keep.add(current)
            stack.extend(self.course.prerequisites(current))
        edges = {
            (r.from_kc, r.to_kc)
            for r in self.course.relations
            if r.relation == "prerequisite"
            and r.from_kc in keep
            and r.to_kc in keep
        }
        return keep, edges

    # -- primary_route：从当前推荐到主目标的真实 DAG 路径 -------------------
    def primary_route(
        self,
        mastery_map: Dict[str, Optional[float]],
        misconception_map: Optional[Dict[str, List[str]]] = None,
        recent_error_map: Optional[Dict[str, bool]] = None,
        start_kc: Optional[str] = None,
        max_len: int = 8,
    ) -> List[str]:
        """给用户一条容易理解的主要学习线（§24）。

        从 current_recommended_kc 出发，沿真实 DAG 边走到某个 primary target。
        未来 locked 节点允许存在；保证 route[i] → route[i+1] 的边真实存在。
        """
        if not self.course.components:
            return []
        path_ordered = self.recommended_path(mastery_map, misconception_map, recent_error_map)
        cur = start_kc or (path_ordered[0] if path_ordered else None)
        if cur is None:
            cur = next((c.kc_id for c in self.course.components), None)
        if cur is None:
            return []
        # 优先目标：从候选 target 中选当前推荐可达的（沿依赖方向）。
        targets = [t for t in self.target_kcs if t in self.course.all_dependents_transitive(cur)] or list(self.target_kcs)
        # 选择离 cur 最远的 target（更完整的主线）。
        def depth_to(t: str) -> int:
            return len(self._path_to(cur, t))
        primary = max(targets, key=depth_to) if targets else cur
        route = self._path_to(cur, primary)
        return route[:max_len]

    def _path_to(self, start: str, goal: str) -> List[str]:
        """BFS 沿 prerequisite 依赖方向（start → goal）找一条真实路径。"""
        if start == goal:
            return [start]
        from collections import deque
        prev: Dict[str, Optional[str]] = {start: None}
        queue = deque([start])
        visited = {start}
        while queue:
            node = queue.popleft()
            for d in self.course.dependents(node):
                if d in visited:
                    continue
                visited.add(d)
                prev[d] = node
                if d == goal:
                    break
                queue.append(d)
        if goal not in prev:
            # 不可达（goal 在 start 上游等）：退化为单节点。
            return [start]
        path: List[str] = []
        cur: Optional[str] = goal
        while cur is not None:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()
        return path

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
