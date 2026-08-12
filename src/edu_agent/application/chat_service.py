"""ChatService：唯一的普通对话实现（无课程 / 有课程 / 有课程+计划步骤）。

- Conversation ownership：conversation_id 必须属于当前 user 且 course 匹配，否则拒绝（404）。
- RAG：真正加载持久化 chunks（load_chunks(course_id)），按课程隔离，不跨课程检索。
- plan_step_id：校验 step 属于 user+course 的 current plan；事件 kc_id=step.kc_id。
- 画像意图：explicit intent → targeted mutation（多技能按 和/、/逗号 拆分，互不覆盖）。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.adaptive.chat_context import build_chat_context, chat_context_to_prompt
from edu_agent.application.learning_context_service import resolve_bundle_and_course
from edu_agent.learner_model.service import LearnerModelService

logger = logging.getLogger(__name__)

_SYSTEM_ROLE = (
    "你是一名友好的学习助手。根据提供的课程与学习者上下文回答问题；"
    "如果没有课程上下文，作为普通 AI 助手聊天。\n"
    "输出格式：使用标准 Markdown；简单回答不要滥用标题；代码必须使用 fenced code block；"
    "行内数学用 $...$，块级数学用 $$...$$，不要把公式放进代码块反引号；不输出 HTML。\n"
    "禁止输出练习题、测试题或测验；讲解时可以使用概念解释、示例、案例和代码演示。"
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _conversation_title(message: str) -> str:
    """首条用户消息 → 对话标题（V1 不调 LLM，纯规则：去空白 + 36 字截断）。"""
    text = re.sub(r"\s+", " ", message).strip()
    if len(text) <= 36:
        return text
    return text[:36].rstrip() + "\u2026"


# ---------------------------------------------------------------------------
# UserMemoryIntentExtractor：明确画像修改语义
# ---------------------------------------------------------------------------

_PATTERNS: List[Dict[str, Any]] = [
    # 我会 X / 我熟悉 X / 我用过 X / 我做过 X → profile fact（positive）
    # 支持多技能："我会 Python 和 Java" → skill:python + skill:java
    {"type": "fact_pos", "regex": r"(?:我会|我熟悉|我了解|我用过|我学过|我掌握|我做过)\s*(.+?)(?:[。，,.!?！？]|$)",
     "value": lambda m: m.group(1).strip()},
    # 我没有 X 基础 / 我不懂 X → fact（negative）
    {"type": "fact_neg", "regex": r"(?:我没有|我没什么|完全不懂|没学过|不会|不熟悉)\s*(.+?)(?:基础)?(?:[。，,.!?！？]|$)",
     "value": lambda m: m.group(1).strip()},
    # 以后少举例 / 简洁一点 → preference（long-term）
    {"type": "pref", "regex": r"(?:以后|之后|今后).{0,6}(?:少举例|不要举例|直接一点|简洁|简短|简单点|别啰嗦)",
     "pref_key": "concise_first", "direction": "pos"},
    {"type": "pref", "regex": r"(?:以后|之后|今后).{0,6}(?:多举例|举例子|给例子|详细一点|讲详细)",
     "pref_key": "worked_example", "direction": "pos"},
    # 忘记我做过 X → delete fact/memory（按 normalized 匹配已存在键）
    {"type": "forget", "regex": r"(?:忘记|忘掉|删掉|不再提)\s*(?:我(?:做过|会|学过|用过)?)?\s*(.+?)(?:项目|东西|事)?(?:[。，,.!?！？]|$)",
     "forget_raw": lambda m: m.group(1)},
]

_SPLIT_RE = re.compile(r"(?:以及|和|与|、|[,，]|及)")  # 只按明确连接词拆分，绝不按空格


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip()).strip("-")
    return slug[:24] or "unknown"


def _skill_key(value: str) -> str:
    """规范化技能键：取首词并小写。例如「Python 基础」→ python，「Java 面向对象」→ java。"""
    text = (value or "").strip()
    head = text.split()[0] if text.split() else text
    return _slug(head).lower() or _slug(text).lower()


def _split_skills(raw: str) -> List[str]:
    """「Python 和 Java」→ [Python, Java]；无分隔符则整体。"""
    parts = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()]
    # 过滤过短片段（如"基础"、"中"）
    return [p for p in parts if len(p) >= 2] or ([raw.strip()] if raw.strip() else [])


def extract_memory_intents(message: str) -> List[Dict[str, Any]]:
    """识别用户明确画像修改意图（结构化 mutation；多技能拆分）。"""
    intents: List[Dict[str, Any]] = []
    for pat in _PATTERNS:
        m = re.search(pat["regex"], message)
        if not m:
            continue
        if pat["type"] == "fact_pos":
            for skill in _split_skills(pat["value"](m)):
                intents.append({"action": "set_fact", "fact_key": f"skill:{_skill_key(skill)}",
                                "fact_value": skill, "category": "background"})
        elif pat["type"] == "fact_neg":
            for skill in _split_skills(pat["value"](m)):
                intents.append({"action": "set_fact", "fact_key": f"no_{_skill_key(skill)}",
                                "fact_value": {"level": "none"}, "category": "background"})
        elif pat["type"] == "pref":
            intents.append({"action": "set_preference", "preference_key": pat["pref_key"],
                            "direction": pat["direction"]})
        elif pat["type"] == "forget":
            intents.append({"action": "delete_fact", "forget_raw": pat["forget_raw"](m)})
    return intents


def _find_forgettable_keys(user_id: str, course_id: str, raw: str,
                           learner: LearnerModelService) -> List[str]:
    """按 normalized token 匹配用户已有 fact/memory（global + 当前 course），
    返回真正存在的可删键；匹配不到返回空（不误删）。"""
    target = _slug(raw).lower()
    keys: List[str] = []
    if not target:
        return keys
    # normalized exact：skill:java 只匹配 skill:java / no_java，不匹配 skill:javascript
    for fact in learner.repo.list_profile_facts(user_id):
        fact_key = (fact.get("fact_key") or "").lower()
        if fact_key == f"skill:{target}" or fact_key == f"no_{target}":
            keys.append(fact["fact_key"])
            continue
        # value 用 token boundary 匹配（避免 Java 命中 JavaScript）
        fact_value = str(fact.get("fact_value_json") or "").lower()
        if re.search(rf"(^|[^a-z0-9\u4e00-\u9fff]){re.escape(target)}(?=[^a-z0-9\u4e00-\u9fff]|$)", fact_value):
            keys.append(fact["fact_key"])
    # memory 同样 token boundary（global + 当前 course）
    for mem in learner.repo.list_effective_memories(user_id, course_id):
        content = str(mem.get("content") or "").lower()
        if re.search(rf"(^|[^a-z0-9\u4e00-\u9fff]){re.escape(target)}(?=[^a-z0-9\u4e00-\u9fff]|$)", content):
            keys.append(f"memory:{mem['memory_id']}")
    return list(dict.fromkeys(keys))


def apply_memory_intents(user_id: str, course_id: str, intents: List[Dict[str, Any]],
                         learner: LearnerModelService) -> List[str]:
    """把明确意图写入 Learner Model（结构化 mutation，非 LLM overwrite）。"""
    applied: List[str] = []
    for intent in intents:
        action = intent["action"]
        try:
            if action == "set_fact":
                learner.set_profile_fact(user_id, intent["fact_key"], intent["fact_value"],
                                         category=intent.get("category", "background"))
                applied.append(f"fact:{intent['fact_key']}")
            elif action == "set_preference":
                learner.set_preference(user_id, intent["preference_key"],
                                       direction=intent.get("direction", "pos"),
                                       course_id=course_id)
                applied.append(f"pref:{intent['preference_key']}")
            elif action == "delete_fact":
                raw = intent.get("forget_raw", "")
                keys = _find_forgettable_keys(user_id, course_id, raw, learner)
                for key in keys:
                    if key.startswith("memory:"):
                        learner.delete_memory(user_id, key.split(":", 1)[1])
                    else:
                        learner.delete_profile_fact(user_id, key)
                    applied.append(f"deleted:{key}")
                if not keys:
                    applied.append(f"delete:no-match:{_slug(raw)}")
        except Exception:  # noqa: BLE001 - 画像写入失败不影响对话
            logger.warning("[chat] memory intent apply failed: action=%s", action, exc_info=True)
    return applied


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------


class ChatService:
    def __init__(self, learner: Optional[LearnerModelService] = None) -> None:
        self._learner = learner or LearnerModelService()

    def create_conversation(self, user_id: str, course_id: Optional[str] = None) -> dict:
        """新建一个 conversation（「新对话」用，不再复用已有主会话）。"""
        learner = self._learner
        learner.ensure_learner(user_id)
        if course_id and learner.repo.get_user_course(user_id, course_id) is None:
            raise KeyError(f"course not found: {course_id}")
        conv_id = f"CONV-{uuid.uuid4().hex[:12]}"
        learner.repo.upsert_conversation(
            {"conversation_id": conv_id, "user_id": user_id, "course_id": course_id or "",
             "title": None, "created_at": _now_iso(), "updated_at": _now_iso()}
        )
        return {"conversation_id": conv_id, "course_id": course_id}

    def list_conversations(
        self, user_id: str, course_id: Optional[str], limit: int = 6
    ) -> List[dict]:
        """最近对话列表：course_id 为空 = General；否则该 Course 的对话。

        title 已由 repository 做 COALESCE(fallback 首条 user 消息)，这里再 normalize/truncate。
        给定 course_id 时先校验归属（ownership 优先），否则 KeyError → 404（信息隐藏）。
        """
        if course_id:
            if self._learner.repo.get_user_course(user_id, course_id) is None:
                raise KeyError(f"course not found: {course_id}")
        rows = self._learner.repo.list_conversations(user_id, course_id or "", limit)
        return [
            {
                "conversation_id": r["conversation_id"],
                "course_id": r["course_id"] or None,
                "title": _conversation_title(r.get("title") or ""),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def chat(
        self,
        user_id: str,
        message: str,
        course_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        plan_step_id: Optional[str] = None,
    ) -> dict:
        """发一条消息并返回 AI 回复。

        顺序（保证当前消息在 LLM Prompt 中只出现一次）：
        resolve conversation → 画像意图 → plan_step 校验 → 加载 PRIOR history
        → 落库当前用户消息 → 事件 → 构建上下文 → LLM(prior history, message)
        → 落库 AI 回复 → 事件。

        conversation_id：必须属于当前 user 且 course 匹配，否则拒绝（KeyError → 404）。
        plan_step_id：显式传入但不存在/不属于当前 user+course → KeyError → 404（不静默降级）。
        """
        learner = self._learner
        learner.ensure_learner(user_id)
        if course_id:
            # ownership 优先：先确认课程属于当前 user，再 ensure_course。
            # 否则非法 course_id 会经 ensure_course 产生 ghost learner_course_state。
            if learner.repo.get_user_course(user_id, course_id) is None:
                raise KeyError(f"course not found: {course_id}")
            learner.ensure_course(user_id, course_id)

        # 1) plan_step 校验：必须在任何副作用（建会话 / 写画像 / 写事件 / 调 LLM）之前。
        # 显式 plan_step_id 必须伴随有效 course_id；否则无法定位归属，直接 404（绝不静默降级）。
        # 放在 conversation 创建与画像写入之前，保证非法 step 不会留下脏数据
        # （空 conversation / Rust profile fact / memory / step event）。
        step: Optional[dict] = None
        if plan_step_id and not course_id:
            raise KeyError("plan_step_id requires course_id")
        if course_id and plan_step_id:
            from edu_agent.application.study_plan_service import get_step

            step = get_step(user_id, course_id, plan_step_id, learner)  # KeyError → 404

        # 2) 会话（ownership 校验：user + course 都必须匹配；校验通过后才创建）
        conv = self._resolve_conversation(user_id, course_id, conversation_id)

        # 3) 画像修改意图（明确语义才写；course 级偏好落当前课程）
        intents = extract_memory_intents(message)
        applied = apply_memory_intents(user_id, course_id or "", intents, learner)

        # 4) 先加载 PRIOR history（不含当前消息）→ Prompt 中当前消息只出现一次
        history = self._recent_history(conv["conversation_id"], limit=8)

        # 5) 用户消息落库（metadata 保留 step 上下文）
        metadata: Dict[str, Any] = {"course_id": course_id}
        if step:
            metadata["plan_step_id"] = step["step_id"]
            metadata["kc_id"] = step.get("kc_id", "")
            metadata["stage_title"] = step.get("stage_title", "")
            metadata["step_title"] = step.get("title", "")
        user_msg_id = f"MSG-{uuid.uuid4().hex[:12]}"
        learner.repo.insert_message(
            {"message_id": user_msg_id, "conversation_id": conv["conversation_id"],
             "role": "user", "content": message, "created_at": _now_iso(),
             "metadata_json": json.dumps(metadata, ensure_ascii=False)}
        )
        # 标题：第一次用户消息后，若 title 仍为空 → 生成（V1 不调 LLM，纯规则截断）；
        # 之后不随聊天自动修改。兼容旧开发数据（title=NULL）由 repository COALESCE 处理。
        if not (conv.get("title") or "").strip():
            conv_title = _conversation_title(message)
            if conv_title:
                learner.repo.set_conversation_title(conv["conversation_id"], conv_title)
                conv = {**conv, "title": conv_title}
        # 事件：有 step 时 kc_id = step.kc_id（真实 KC，不是 PLANSTEP id）
        learner.record_event({"event_type": "CHAT_MESSAGE_SENT", "user_id": user_id,
                              "course_id": course_id or "",
                              "kc_id": (step or {}).get("kc_id", ""),
                              "session_id": conv["conversation_id"],
                              "payload": {"message": message[:120],
                                          "plan_step_id": (step or {}).get("step_id", ""),
                                          "step_title": (step or {}).get("title", "")}})

        # 6) 上下文（RAG query = step.title + message；真加载持久化 chunks）
        context_text = self._build_context(user_id, course_id, message, step)
        reply = self._llm_reply(message, context_text, history)

        # 7) AI 回复落库
        ai_msg_id = f"MSG-{uuid.uuid4().hex[:12]}"
        learner.repo.insert_message(
            {"message_id": ai_msg_id, "conversation_id": conv["conversation_id"],
             "role": "assistant", "content": reply, "created_at": _now_iso(),
             "metadata_json": json.dumps(metadata, ensure_ascii=False)}
        )
        learner.record_event({"event_type": "CHAT_RESPONSE_DELIVERED", "user_id": user_id,
                              "course_id": course_id or "", "session_id": conv["conversation_id"]})

        context_type = "plan_step" if step else ("course" if course_id else "general")
        return {
            "message_id": ai_msg_id,
            "conversation_id": conv["conversation_id"],
            "content": reply,
            "course_id": course_id,
            "created_at": _now_iso(),
            "profile_updates": applied,
            "context": {
                "type": context_type,
                "course_id": course_id,
                "plan_step_id": step["step_id"] if step else None,
                "step_title": step.get("title", "") if step else "",
            },
        }

    def get_conversation(self, user_id: str, course_id: Optional[str] = None,
                         conversation_id: Optional[str] = None,
                         limit: int = 100) -> dict:
        """GET 历史：纯读取，不创建 conversation（避免 GET 产生 DB write）。

        没有 conversation 时返回 conversation_id=None + 空 history（200），
        前端据此显示 Empty State，而不是「无法加载历史消息」。

        ownership：GET 历史也必须校验 course 归属，否则 404（与 POST 一致），
        避免「USER-B 访问 USER-A course 返回 200/[]」把无权限与空历史混为一谈。
        （合法 owner 的空白课程仍返回 200/[]，保留 fresh-course empty state。）

        返回最近 limit 条（DESC 取最新再 reverse 成 chronological），不是最早 limit 条；
        超长会话只回最新 N 条（与 LLM prompt 的 _recent_history 不同层级，互不破坏）。
        """
        learner = self._learner
        if course_id:
            # ownership 优先：当前用户不拥有该 course → 404（信息隐藏）。
            if learner.repo.get_user_course(user_id, course_id) is None:
                raise KeyError(f"course not found: {course_id}")
        conv = self._resolve_conversation(
            user_id, course_id, conversation_id, create_if_missing=False
        )
        if conv is None:
            return {"conversation_id": None, "course_id": course_id, "messages": []}
        messages = learner.repo.list_recent_messages(conv["conversation_id"], limit=limit)
        return {"conversation_id": conv["conversation_id"], "course_id": course_id,
                "messages": [{"message_id": m["message_id"], "role": m["role"],
                              "content": m["content"], "created_at": m["created_at"],
                              "metadata": _safe_json(m.get("metadata_json"))}
                             for m in messages]}

    # ------------------------------------------------------------------
    def _resolve_conversation(self, user_id: str, course_id: Optional[str],
                              conversation_id: Optional[str],
                              create_if_missing: bool = True) -> Optional[dict]:
        """ownership-safe 会话解析：conversation_id 必须 user+course 匹配，否则拒绝。

        create_if_missing：True 时（POST chat）无 conversation 自动创建；
        False 时（GET 历史）无 conversation 返回 None，由调用方返回空 history，不写库。
        """
        repo = self._learner.repo
        if conversation_id:
            conv = repo.get_conversation_for_user(user_id, conversation_id)
            if conv is None:
                raise KeyError(f"conversation not found: {conversation_id}")
            if (course_id or "") != (conv.get("course_id") or ""):
                raise KeyError(f"conversation not found: {conversation_id}")
            return conv
        conv = repo.get_course_conversation(user_id, course_id or "")
        if conv is None:
            if not create_if_missing:
                return None
            conv_id = f"CONV-{uuid.uuid4().hex[:12]}"
            repo.upsert_conversation(
                {"conversation_id": conv_id, "user_id": user_id, "course_id": course_id or "",
                 "title": None, "created_at": _now_iso(), "updated_at": _now_iso()}
            )
            conv = repo.get_conversation(conv_id)
        return conv or {"conversation_id": "", "user_id": user_id, "course_id": course_id or ""}

    def _build_context(self, user_id: str, course_id: Optional[str],
                       message: str, plan_step: Optional[dict] = None) -> str:
        if not course_id:
            return ""  # 普通聊天不加载课程画像
        # 最低保障：课程显示名 + 目标 + 计划摘要（个性化失败也保留，绝不变普通聊天）
        repo = self._learner.repo
        course_row = repo.get_user_course(user_id, course_id)
        # 优先 user_courses.display_name（用户 rename 后的名字）；
        # 内置课程首次访问时 display_name 即为内置 title 的副本，无需再用 domain title 覆盖。
        course_title = (course_row or {}).get("display_name") or course_id
        try:
            bundle, course = resolve_bundle_and_course(user_id, course_id, self._learner)
            plan = repo.get_plan(user_id, course_id)
            plan_summary = (plan or {}).get("summary", "")
            # RAG query：step.title + message 提升相关性；正式路径必须用真实问题
            query = message
            if plan_step and plan_step.get("title"):
                query = f"{plan_step['title']} {message}".strip()
            rag_hits = self._rag(user_id, course_id, query, top_k=3)
            ctx = build_chat_context(bundle, repo, course_id,
                                     course_title=course_title,
                                     plan_summary=plan_summary or "",
                                     plan_step=plan_step, rag_hits=rag_hits)
            return chat_context_to_prompt(ctx)
        except Exception:  # noqa: BLE001 - 个性化失败只丢个性化字段
            logger.warning("[chat] build context degraded: user=%s course=%s", user_id, course_id, exc_info=True)
            lines = [f"当前课程：{course_title}"]
            goal = self._current_goal_summary(user_id, course_id)
            if goal:
                lines.append(f"学习目标：{goal}")
            plan = repo.get_plan(user_id, course_id)
            if plan and plan.get("summary"):
                lines.append(f"计划摘要：{plan['summary']}")
            return "\n".join(lines)

    def _current_goal_summary(self, user_id: str, course_id: str) -> str:
        """复用 LearnerModelService 的 active goal 解析（course_state.current_goal_id 优先）。

        resolve_active_goal 返回 Goal Pydantic 模型（非 dict），必须用属性访问。
        """
        try:
            goal = self._learner.resolve_active_goal(user_id, course_id)
            if goal:
                target = goal.target or ""
                name = goal.goal_name or ""
                return target or name
        except Exception:  # noqa: BLE001
            logger.warning("[chat] resolve active goal failed", exc_info=True)
        return ""

    def _rag(self, user_id: str, course_id: str, message: str, top_k: int = 3) -> List[dict]:
        """课程知识库检索：ready-source gate（metadata 存在 + status=ready）+ user+course 双隔离。"""
        try:
            from edu_agent.application.course_source_service import load_ready_course_chunks
            from edu_agent.tools.course_kb import CourseKnowledgeBase

            chunks = load_ready_course_chunks(user_id, course_id, learner=self._learner)
            if not chunks:
                return []
            kb = CourseKnowledgeBase.from_chunks(chunks, user_id=user_id, course_id=course_id)
            hits = kb.search(message, top_k=top_k)
            return [{"title": h.doc_title, "text": h.text[:400], "url": h.source_url} for h in hits]
        except Exception:  # noqa: BLE001 - RAG 失败不影响聊天
            logger.warning("[chat] rag search failed: user=%s course=%s", user_id, course_id, exc_info=True)
            return []

    def _recent_history(self, conversation_id: str, limit: int = 8) -> List[Dict[str, str]]:
        """最近 N 条历史（chronological 旧→新）；在插入当前消息前调用。"""
        messages = self._learner.repo.list_recent_messages(conversation_id, limit=limit)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def _llm_reply(self, message: str, context_text: str, history: List[Dict[str, str]]) -> str:
        """调用 LLM；无模型/失败时降级为可用的基础回复。"""
        try:
            from langchain_core.prompts import ChatPromptTemplate

            from edu_agent.core.llm import get_kb_llm

            context_block = f"\n课程与学习者上下文：\n{context_text}\n" if context_text else ""
            prompt = ChatPromptTemplate.from_template(
                "{system}"
                "{context_block}"
                "历史对话：\n{history}\n\n用户：{message}\n\n助手："
            )
            history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:]) or "（无）"
            response = (prompt | get_kb_llm(temperature=0.4)).invoke(
                {"system": _SYSTEM_ROLE, "context_block": context_block,
                 "history": history_text, "message": message}
            )
            from edu_agent.core.agent_runner import model_to_text
            return model_to_text(response).strip() or _fallback_reply(message)
        except Exception:  # noqa: BLE001 - 无模型环境降级
            logger.warning("[chat] llm reply failed, using fallback", exc_info=True)
            return _fallback_reply(message)


def _safe_json(raw: Optional[str]) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def _fallback_reply(message: str) -> str:
    """降级回复（未配置 LLM 时）。"""
    return (
        "（演示模式，未配置模型）我听到了你的问题：\n\n"
        f"{message}\n\n"
        "配置 LLM API Key 后可获得完整回答。"
    )
