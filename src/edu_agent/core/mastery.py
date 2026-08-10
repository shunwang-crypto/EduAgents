"""知识掌握度（Mastery）核心：自适应学习的"状态中枢"。

设计红线（与主项目一致）：
- 掌握度数值只由这里的**确定性规则**更新（答对 +0.3 / 答错 -0.25，夹在 [0,1]）；
- LLM 只做讲解 / 评审 / 表达层，**不得改写掌握度**；
- 纯函数、无依赖，可单测。

状态结构：``{node_id: {"p": 0.3, "attempts": 0, "correct": 0}}``。
"""

from __future__ import annotations

from typing import Dict, List, Optional

MASTERED_THRESHOLD = 0.7
CORRECT_DELTA = 0.3
WRONG_DELTA = 0.25


def new_mastery() -> Dict[str, dict]:
    """返回空掌握度状态。"""
    return {}


def get_p(mastery: Dict[str, dict], node_id: str) -> float:
    """读取某节点掌握度 p（未学过默认 0.3 起步）。"""
    return mastery.get(node_id, {}).get("p", 0.3)


def update_mastery(
    mastery: Dict[str, dict],
    node_id: str,
    correct: bool,
) -> Dict[str, dict]:
    """根据一次作答更新掌握度（确定性规则，返回新状态 dict）。

    答对 p += 0.3，答错 p -= 0.25，夹在 [0, 1]；attempts/correct 累计。
    """
    state = mastery.get(node_id, {"p": 0.3, "attempts": 0, "correct": 0})
    delta = CORRECT_DELTA if correct else -WRONG_DELTA
    new_p = max(0.0, min(1.0, state["p"] + delta))
    mastery[node_id] = {
        "p": round(new_p, 3),
        "attempts": state["attempts"] + 1,
        "correct": state["correct"] + (1 if correct else 0),
    }
    return mastery


def is_mastered(mastery: Dict[str, dict], node_id: str, threshold: float = MASTERED_THRESHOLD) -> bool:
    """节点是否已掌握（p >= 阈值）。"""
    return get_p(mastery, node_id) >= threshold


def _prerequisites_ready(mastery: Dict[str, dict], node_id: str, prereq_of: Dict[str, List[str]]) -> bool:
    """节点的所有前置是否都已掌握。"""
    for prereq in prereq_of.get(node_id, []):
        if not is_mastered(mastery, prereq):
            return False
    return True


def next_node(
    learning_sequence: List[str],
    prerequisites: List[str],
    mastery: Dict[str, dict],
    current: Optional[str] = None,
    threshold: float = MASTERED_THRESHOLD,
) -> Optional[str]:
    """推荐"下一步该学"的节点。

    规则：按 learning_sequence 顺序，找第一个「前置已掌握、自身未达标」的节点；
    若全部达标返回 None（学习完成）。
    """
    prereq_of: Dict[str, List[str]] = {}
    for item in prerequisites:
        parts = [part.strip() for part in item.replace("，", ",").split(",") if part.strip()]
        if len(parts) >= 2:
            prereq_of.setdefault(parts[-1], []).extend(parts[:-1])

    for node_id in learning_sequence:
        if is_mastered(mastery, node_id, threshold):
            continue
        if _prerequisites_ready(mastery, node_id, prereq_of):
            return node_id
    return None
