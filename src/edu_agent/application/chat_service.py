"""ChatService：唯一的普通对话实现（有课程 → 轻量课程上下文；无课程 → 普通聊天）。

- 保存 chat_conversations / chat_messages（每课程一个主 conversation；无课程 general）。
- UserMemoryIntentExtractor：只处理明确画像修改语义（我会/没有基础/以后少举例/忘记做过），
  禁止每条消息重写画像。
- RAG：有课程且有知识库命中时作为可选参考，不做独立 KBQA。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.adaptive.chat_context import build_chat_context, chat_context_to_prompt
from edu_agent.application.learning_context_service import resolve_bundle_and_course
from edu_agent.learner_model.service import LearnerModelService

_SYSTEM_ROLE = (
    "你是一名友好的学习助手。根据提供的课程与学习者上下文回答问题；"
    "如果没有课程上下文，作为普通 AI 助手聊天。回答简洁自然，不要输出练习题或测验。"
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# UserMemoryIntentExtractor：明确画像修改语义
# ---------------------------------------------------------------------------

_PATTERNS: List[Dict[str, Any]] = [
    # 我会 X / 我熟悉 X / 我用过 X → profile fact（positive）
    {"type": "fact_pos", "regex": r"(?:我会|我熟悉|我了解|我用过|我学过|我掌握)\s*(.+?)(?:[。，,.!?！？]|$)",
     "fact_key": lambda m: "skill",
     "value": lambda m: m.group(1).strip()},
    # 我没有 X 基础 / 我不懂 X → fact（negative）
    {"type": "fact_neg", "regex": r"(?:我没有|我没什么|完全不懂|没学过)\s*(.+?)(?:基础)?(?:[。，,.!?！？]|$)",
     "fact_key": lambda m: f"no_{_slug(m.group(1))}",
     "value": lambda m: m.group(1).strip()},
    # 以后少举例 / 简洁一点 → preference（long-term）
    {"type": "pref", "regex": r"(?:以后|之后|今后).{0,6}(?:少举例|不要举例|直接一点|简洁|简短|简单点|别啰嗦)",
     "pref_key": "concise_first", "direction": "pos"},
    {"type": "pref", "regex": r"(?:以后|之后|今后).{0,6}(?:多举例|举例子|给例子|详细一点|讲详细)",
     "pref_key": "worked_example", "direction": "pos"},
    # 忘记我做过 X → delete fact/memory
    {"type": "forget", "regex": r"(?:忘记|忘掉|删掉|不再提)\s*(?:我(?:做过|会|学过|用过)?)?\s*(.+?)(?:项目|东西|事)?(?:[。，,.!?！？]|$)",
     "forget_key": lambda m: _slug(m.group(1).lower())},
]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip()).strip("-")
    return slug[:24] or "unknown"


def extract_memory_intents(message: str) -> List[Dict[str, Any]]:
    """识别用户明确画像修改意图（结构化 mutation）。"""
    intents: List[Dict[str, Any]] = []
    for pat in _PATTERNS:
        m = re.search(pat["regex"], message)
        if not m:
            continue
        if pat["type"] == "fact_pos":
            intents.append({"action": "set_fact", "fact_key": pat["fact_key"](m),
                            "fact_value": pat["value"](m), "category": "background"})
        elif pat["type"] == "fact_neg":
            intents.append({"action": "set_fact", "fact_key": pat["fact_key"](m),
                            "fact_value": {"level": "none"}, "category": "background"})
        elif pat["type"] == "pref":
            intents.append({"action": "set_preference", "preference_key": pat["pref_key"],
                            "direction": pat["direction"]})
        elif pat["type"] == "forget":
            intents.append({"action": "delete_fact", "fact_key": pat["forget_key"](m)})
    return intents


def apply_memory_intents(user_id: str, intents: List[Dict[str, Any]],
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
                                       direction=intent.get("direction", "pos"))
                applied.append(f"pref:{intent['preference_key']}")
            elif action == "delete_fact":
                learner.delete_profile_fact(user_id, intent["fact_key"])
                applied.append(f"deleted:{intent['fact_key']}")
        except Exception:  # noqa: BLE001 - 画像写入失败不影响对话
            continue
    return applied


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------


class ChatService:
    def __init__(self, learner: Optional[LearnerModelService] = None) -> None:
        self._learner = learner or LearnerModelService()

    def chat(
        self,
        user_id: str,
        message: str,
        course_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        extra_requirement: str = "",
    ) -> dict:
        """发一条消息并返回 AI 回复。"""
        learner = self._learner
        learner.ensure_learner(user_id)
        if course_id:
            learner.ensure_course(user_id, course_id)

        # 1) 会话（每课程一个主 conversation；无课程 general）
        conv = self._get_or_create_conversation(user_id, course_id, conversation_id)

        # 2) 画像修改意图（明确语义才写，普通消息不碰画像）
        intents = extract_memory_intents(message)
        applied = apply_memory_intents(user_id, intents, learner)

        # 3) 用户消息落库
        user_msg_id = f"MSG-{uuid.uuid4().hex[:12]}"
        learner.repo.insert_message(
            {"message_id": user_msg_id, "conversation_id": conv["conversation_id"],
             "role": "user", "content": message, "created_at": _now_iso(), "metadata_json": "{}"}
        )
        learner.record_event({"event_type": "CHAT_MESSAGE_SENT", "user_id": user_id,
                              "course_id": course_id or "", "session_id": conv["conversation_id"],
                              "payload": {"message": message[:120]}})

        # 4) 上下文
        context_text = self._build_context(user_id, course_id)
        history = self._recent_history(conv["conversation_id"], limit=8)
        reply = self._llm_reply(message, context_text, history, extra_requirement)

        # 5) AI 回复落库
        ai_msg_id = f"MSG-{uuid.uuid4().hex[:12]}"
        learner.repo.insert_message(
            {"message_id": ai_msg_id, "conversation_id": conv["conversation_id"],
             "role": "assistant", "content": reply, "created_at": _now_iso(), "metadata_json": "{}"}
        )
        learner.record_event({"event_type": "CHAT_RESPONSE_DELIVERED", "user_id": user_id,
                              "course_id": course_id or "", "session_id": conv["conversation_id"]})

        return {
            "message_id": ai_msg_id,
            "conversation_id": conv["conversation_id"],
            "content": reply,
            "course_id": course_id,
            "created_at": _now_iso(),
            "profile_updates": applied,
        }

    def get_conversation(self, user_id: str, course_id: Optional[str] = None,
                         conversation_id: Optional[str] = None) -> dict:
        learner = self._learner
        conv = self._get_or_create_conversation(user_id, course_id, conversation_id)
        messages = learner.repo.list_messages(conv["conversation_id"])
        return {"conversation_id": conv["conversation_id"], "course_id": course_id,
                "messages": [{"message_id": m["message_id"], "role": m["role"],
                              "content": m["content"], "created_at": m["created_at"]}
                             for m in messages]}

    # ------------------------------------------------------------------
    def _get_or_create_conversation(self, user_id: str, course_id: Optional[str],
                                    conversation_id: Optional[str]) -> dict:
        repo = self._learner.repo
        if conversation_id:
            conv = repo.get_conversation(conversation_id)
            if conv is not None:
                return conv
        conv = repo.get_course_conversation(user_id, course_id or "")
        if conv is None:
            conv_id = f"CONV-{uuid.uuid4().hex[:12]}"
            repo.upsert_conversation(
                {"conversation_id": conv_id, "user_id": user_id, "course_id": course_id or "",
                 "title": None, "created_at": _now_iso(), "updated_at": _now_iso()}
            )
            conv = repo.get_conversation(conv_id)
        return conv or {"conversation_id": "", "user_id": user_id, "course_id": course_id or ""}

    def _build_context(self, user_id: str, course_id: Optional[str]) -> str:
        if not course_id:
            return ""  # 普通聊天不加载课程画像
        try:
            bundle, _course = resolve_bundle_and_course(user_id, course_id, self._learner)
            plan = self._learner.repo.get_plan(user_id, course_id)
            plan_summary = (plan or {}).get("summary", "")
            rag_hits = self._rag(course_id, "", top_k=0)  # 上下文构建不强制 RAG
            ctx = build_chat_context(bundle, self._learner.repo, course_id,
                                     plan_summary=plan_summary or "", rag_hits=rag_hits)
            return chat_context_to_prompt(ctx)
        except Exception:  # noqa: BLE001 - 上下文失败走普通聊天
            return ""

    def _rag(self, course_id: str, message: str, top_k: int = 3) -> List[dict]:
        """课程知识库检索（可选能力，不强制教育化）。"""
        try:
            from edu_agent.tools.course_kb import CourseKnowledgeBase

            kb = CourseKnowledgeBase()
            if not kb.chunks:
                return []
            hits = kb.search(message, top_k=top_k)
            return [{"title": h.doc_title, "text": h.text[:400]} for h in hits]
        except Exception:  # noqa: BLE001
            return []

    def _recent_history(self, conversation_id: str, limit: int = 8) -> List[Dict[str, str]]:
        messages = self._learner.repo.list_messages(conversation_id, limit=limit)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def _llm_reply(self, message: str, context_text: str, history: List[Dict[str, str]],
                   extra_requirement: str = "") -> str:
        """调用 LLM；无模型/失败时降级为可用的基础回复。"""
        try:
            from langchain_core.prompts import ChatPromptTemplate

            from edu_agent.core.llm import get_kb_llm

            context_block = f"\n课程与学习者上下文：\n{context_text}\n" if context_text else ""
            requirement_block = f"\n额外要求：{extra_requirement}\n" if extra_requirement else ""
            prompt = ChatPromptTemplate.from_template(
                "{system}"
                "{context_block}"
                "{requirement_block}"
                "历史对话：\n{history}\n\n用户：{message}\n\n助手："
            )
            history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:]) or "（无）"
            response = (prompt | get_kb_llm(temperature=0.4)).invoke(
                {"system": _SYSTEM_ROLE, "context_block": context_block,
                 "requirement_block": requirement_block, "history": history_text,
                 "message": message}
            )
            return str(response).strip() or _fallback_reply(message)
        except Exception:  # noqa: BLE001 - 无模型环境降级
            return _fallback_reply(message)


def _fallback_reply(message: str) -> str:
    """降级回复（未配置 LLM 时）。"""
    return (
        "（演示模式，未配置模型）我听到了你的问题：\n\n"
        f"{message}\n\n"
        "配置 LLM API Key 后可获得完整回答。"
    )
