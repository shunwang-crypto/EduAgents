"""ChatContextBuilder：普通对话的轻量上下文选择。

只选择当前真正需要的：
- 当前课程（显示名，非 course_id）/ 学习目标 / 学习计划摘要 / 计划进度
- 当前计划步骤（stage / title / objective / prerequisites / difficulty）
- 相关 profile facts / preferences / semantic memories
- 可选 RAG 命中块

不加载整份 Learner Model；不强制教育化；无课程时返回空上下文（普通聊天）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from edu_agent.learner_model.schemas import LearnerStateBundle
from edu_agent.learner_model.repository import LearnerRepository


def build_chat_context(
    bundle: LearnerStateBundle,
    repo: LearnerRepository,
    course_id: str = "",
    course_title: str = "",
    plan_summary: str = "",
    plan_step: Dict[str, Any] | None = None,
    rag_hits: List[Dict[str, Any]] | None = None,
) -> Dict[str, object]:
    """组装 chat 上下文（dict），供 ChatService 注入 prompt。

    course_title：课程显示名（display_name / Domain title），绝不能回退成 course_id 给 LLM。
    plan_step：当前计划步骤 dict（可选），仅当用户从「就此提问」进入时提供。
    """
    profile = bundle.global_state.profile
    goal = bundle.active_goal
    facts = [f for f in repo.list_profile_facts(bundle.user_id) if f.get("status") == "active"]
    prefs = bundle.global_state.preferences.mode_effectiveness
    memories = [m.content for m in bundle.global_state.semantic_memory[:3]]

    context: Dict[str, object] = {
        "course_id": course_id or None,
        "course_title": course_title or (course_id or None),
        "goal_name": goal.goal_name if goal else "",
        "goal_target": goal.target if goal else "",
        "plan_summary": plan_summary or "",
        "progress": bundle.course_state.progress if course_id else 0.0,
        "plan_step": plan_step or None,
        "facts": [{"key": f["fact_key"], "value": f["fact_value_json"]} for f in facts[:6]],
        "preferences": [k for k, v in prefs.items() if v.confidence >= 0.5 and v.score >= 0.6],
        "memories": memories,
        "rag_hits": rag_hits or [],
    }
    return context


def chat_context_to_prompt(ctx: Dict[str, object]) -> str:
    """把 chat 上下文转成注入 LLM 的简短文本。"""
    lines: List[str] = []
    if ctx.get("course_title"):
        lines.append(f"当前课程：{ctx['course_title']}")
    goal_text = ctx.get("goal_target") or ctx.get("goal_name") or ""
    if goal_text:
        lines.append(f"学习目标：{goal_text}")
    if ctx.get("plan_summary"):
        lines.append(f"学习计划摘要：{str(ctx['plan_summary'])[:300]}")
    step = ctx.get("plan_step")
    if step:
        stage_title = step.get("stage_title") or ""
        stage_label = f"{step.get('stage_order', 1)} · {stage_title}" if stage_title else f"阶段 {step.get('stage_order', 1)}"
        lines.append(f"当前计划步骤：阶段{stage_label}")
        lines.append(f"知识点：{step.get('title', '')}")
        if step.get("learning_objective"):
            lines.append(f"学习目标：{step['learning_objective']}")
        prereqs = step.get("prerequisites") or []
        if prereqs:
            lines.append("前置：" + "、".join(prereqs[:5]))
        if step.get("difficulty"):
            lines.append(f"难度：{step['difficulty']}")
    if ctx.get("facts"):
        fact_text = "；".join(f"{f['key']}={f['value']}" for f in ctx["facts"])
        lines.append(f"学生背景：{fact_text}")
    if ctx.get("preferences"):
        lines.append("偏好：希望" + "、".join(ctx["preferences"]))
    if ctx.get("memories"):
        lines.append("长期记忆：" + "；".join(ctx["memories"]))
    if ctx.get("rag_hits"):
        refs = "\n".join(f"- {h.get('title', '')}: {str(h.get('text', ''))[:200]}" for h in ctx["rag_hits"][:3])
        lines.append(f"课程资料参考：\n{refs}")
    return "\n".join(lines)
