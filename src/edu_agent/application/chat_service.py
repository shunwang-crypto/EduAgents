"""ChatService：唯一的普通对话实现（无课程 / 有课程 / 有课程+计划步骤）。

- Conversation ownership：conversation_id 必须属于当前 user 且 course 匹配，否则拒绝（404）。
- RAG：真正加载持久化 chunks（load_chunks(course_id)），按课程隔离，不跨课程检索。
- plan_step_id：校验 step 属于 user+course 的 current plan；事件 kc_id=step.kc_id。
- 画像意图：LLM 语义抽取是主路径（抽取时提供已有画像做去重），确定性正则只在
  LLM 不可用/失败时 fallback；「忘记/删除」永远走确定性规则且先于一切抽取；
  多技能按 和/、/逗号 拆分，互不覆盖。
- 回复与画像抽取并行，但回复最多等待抽取 _MEMORY_WAIT_SECONDS 秒；超时后抽取
  在后台线程自行落库（下一轮生效），绝不阻塞回复返回。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
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
    # 教育背景 / 经历：模型不可用时的保守 fallback；主路径仍由语义抽取判断是否长期稳定。
    {"type": "education", "regex": r"(?:我是|我读的是|我就读于)\s*(.{1,30}?(?:专业|系|学生))(?:[。，,.!?！？]|$)",
     "value": lambda m: m.group(1).strip()},
    {"type": "education", "regex": r"我的专业是\s*(.{1,30}?)(?:[。，,.!?！？]|$)",
     "value": lambda m: m.group(1).strip()},
    {"type": "experience", "regex": r"(?:之前|曾经|最近).{0,8}(?:做过|开发过|参与过|完成过)\s*(.+?)(?:[。，,.!?！？]|$)",
     "value": lambda m: m.group(1).strip()},
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
    # 没有“以后”也可以表达稳定偏好；这是无模型时的保守 fallback，主路径由 LLM 做语义判断。
    {"type": "pref", "regex": r"(?:更喜欢|喜欢|偏好|倾向于).{0,12}(?:代码示例|代码例子|编程示例)",
     "pref_key": "code_example", "direction": "pos"},
    {"type": "pref", "regex": r"(?:不喜欢|不太喜欢|讨厌|避免).{0,12}(?:纯理论|理论讲解|只讲理论)",
     "pref_key": "theory_first", "direction": "neg"},
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
    """确定性画像意图（删除永远走这里；新增/偏好仅在 LLM 不可用时作为 fallback）。

    结构化 mutation；多技能拆分。删除模式优先短路，避免"忘记我做过 X"
    同时命中正向的"我做过 X"。
    """
    intents: List[Dict[str, Any]] = []
    # 删除优先，避免“忘记我做过 X”同时命中正向的“我做过 X”。
    for pat in _PATTERNS:
        if pat["type"] != "forget":
            continue
        match = re.search(pat["regex"], message)
        if match:
            return [{"action": "delete_fact", "forget_raw": pat["forget_raw"](match)}]
    for pat in _PATTERNS:
        if pat["type"] == "forget":
            continue
        m = re.search(pat["regex"], message)
        if not m:
            continue
        if pat["type"] == "education":
            value = pat["value"](m).strip()
            if value:
                intents.append({"action": "set_fact", "fact_key": "education_field",
                                "fact_value": value, "category": "background"})
        elif pat["type"] == "experience":
            value = pat["value"](m).strip()
            if value:
                intents.append({"action": "set_fact", "fact_key": f"experience:{_slug(value)}",
                                "fact_value": value, "category": "experience"})
                intents.append({"action": "add_memory", "content": f"用户曾做过：{value}",
                                "category": "experience", "course_id": ""})
        elif pat["type"] == "fact_pos":
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
    return intents


_ALLOWED_PREFERENCES = {
    "concise_first", "detailed_explanation", "worked_example", "code_example",
    "visual_explanation", "theory_first", "hands_on", "step_by_step", "analogy",
}
_ALLOWED_MEMORY_CATEGORIES = {"experience", "learning_context", "goal"}
_SENSITIVE_TERMS = re.compile(
    r"(密码|口令|token|api[_ -]?key|身份证|手机号|电话|邮箱|住址|精确位置|银行卡|账户|收入|工资|病史|诊断|政治|宗教|"
    r"\b(?:password|secret|credential|email|phone|address|location|financial|health|political|religious?)\b)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|\bsk-[A-Za-z0-9_-]{12,}\b)",
    re.IGNORECASE,
)


# 回复等待画像抽取结果的上限；超时后抽取转后台完成，响应里只缺 profile_updates 增量。
_MEMORY_WAIT_SECONDS = 15

# 成本闸门：无任何自述信号的消息（纯提问 / 指令）不调抽取 LLM。
# 宁可漏过闸门多调一次，也不要收紧到误伤真实自述（英文口语如 I've / my）。
_SELF_REFERENCE_RE = re.compile(
    r"我|本人|自己|以前|之前|曾经|最近|以后|今后|之后|忘记|删掉|不再提"
    r"|\bI\b|\bI'm\b|\bI've\b|\bmy\b|\bMy\b"
)


def _worth_extracting(message: str) -> bool:
    """消息里是否有自述信号，值得调一次抽取 LLM。"""
    text = (message or "").strip()
    return len(text) >= 4 and bool(_SELF_REFERENCE_RE.search(text))


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
    return str(content or "")


def _parse_json_payload(text: str) -> Any:
    """接受裸 JSON 或 fenced JSON，拒绝模型附带的任意自然语言。"""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # 允许模型在 JSON 前后加一句话，但只取第一个完整数组/对象。
        for opener, closer in (("[", "]"), ("{", "}")):
            start, end = raw.find(opener), raw.rfind(closer)
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except (TypeError, ValueError):
                    continue
    return []


def _normalize_ai_intents(payload: Any, course_id: str = "") -> List[Dict[str, Any]]:
    """校验 LLM 输出，确保它只能写入有限的画像字段。"""
    items = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    result: List[Dict[str, Any]] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"set_fact", "set_preference", "add_memory"}:
            # LLM 永远没有删除权限；forget 只由 deterministic extractor 产生。
            continue
        scope = item.get("scope", "global")
        scope = "course" if scope == "course" and course_id else "global"
        scoped_course = course_id if scope == "course" else ""
        if action == "set_preference":
            key = str(item.get("preference_key", "")).strip()
            direction = item.get("direction", "pos")
            if key not in _ALLOWED_PREFERENCES or direction not in {"pos", "neg"}:
                continue
            result.append({"action": action, "preference_key": key, "direction": direction,
                           "course_id": scoped_course})
        elif action == "set_fact":
            key = str(item.get("fact_key", "")).strip().lower()
            value = item.get("fact_value", "")
            if not key or not re.fullmatch(r"[a-z][a-z0-9_:-]{1,63}", key):
                continue
            value_text = (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                          else str(value)).strip()
            if (not value_text or len(value_text) > 160
                    or _SENSITIVE_TERMS.search(key + " " + value_text)
                    or _SENSITIVE_VALUE.search(value_text)):
                continue
            if scope == "course":
                key = f"background:{course_id}:{key}"
            result.append({"action": action, "fact_key": key, "fact_value": value,
                           "category": str(item.get("category") or "background")[:40]})
        else:
            content = re.sub(r"\s+", " ", str(item.get("content", "")).strip())
            category = str(item.get("category", "experience"))
            if category not in _ALLOWED_MEMORY_CATEGORIES or not content or len(content) > 240:
                continue
            if _SENSITIVE_TERMS.search(content) or _SENSITIVE_VALUE.search(content):
                continue
            result.append({"action": action, "content": content, "category": category,
                           "course_id": scoped_course})
    return result


def _existing_profile_text(user_id: str, course_id: str, learner: LearnerModelService) -> str:
    """已有画像摘要（进抽取 prompt，供 LLM 去重）：active facts + 有效 memories。

    与 ChatContext 相同的课程过滤：其他课程的 background:{course} fact 不出现。
    读取失败返回空串（抽取降级为无画像上下文，不中断）。
    """
    try:
        from edu_agent.learner_model.fact_text import humanize_profile_fact

        lines: List[str] = []
        facts: List[str] = []
        for f in learner.repo.list_profile_facts(user_id):
            if f.get("status") != "active":
                continue
            key = f.get("fact_key", "")
            if key.startswith("background:") and not (
                course_id and (key == f"background:{course_id}"
                               or key.startswith(f"background:{course_id}:"))
            ):
                continue
            text = humanize_profile_fact(key, f.get("fact_value_json"))
            if text:
                facts.append(text)
        if facts:
            lines.append("facts：")
            lines.extend(f"- {t}" for t in facts[:12])
        memories = [
            str(m.get("content") or "").strip()
            for m in learner.repo.list_effective_memories(user_id, course_id)
        ]
        memories = [m for m in memories if m][:8]
        if memories:
            lines.append("memories：")
            lines.extend(f"- {m}" for m in memories)
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 - 画像读取失败只影响去重质量
        logger.warning("[chat] load existing profile for extraction failed", exc_info=True)
        return ""


def _extract_ai_memory_intents(
    user_id: str, message: str, history: List[Dict[str, str]],
    course_id: str = "", learner: Optional[LearnerModelService] = None,
) -> Optional[List[Dict[str, Any]]]:
    """用 LLM 从用户自述中提取可长期保存的信息（带已有画像去重）。

    返回 None 表示 LLM 不可用/调用失败（调用方退回确定性规则）；
    返回 [] 表示模型成功判定"本轮无值得保存的信息"（不再走正则，避免误报入库）。
    """
    try:
        from edu_agent.core.llm import get_kb_llm

        recent = "\n".join(f"{h.get('role', 'user')}: {h.get('content', '')[:500]}" for h in history[-6:]) or "（无历史）"
        existing = (
            _existing_profile_text(user_id, course_id, learner)
            if learner is not None else ""
        ) or "（暂无）"
        prompt = f"""你是一位细致的学习助手记忆系统，类似于主流 AI 产品（如 ChatGPT）的"记忆"功能：通过自然对话记住用户值得长期保存的信息，让以后的对话更贴心、更个性化。

【判断标准：哪些信息值得记住】
- 记住：教育背景、专业、技能、项目经历、长期目标、稳定的学习偏好/风格、反复提到的关注点。
- 不记：临时指令（如"这次只回答一句"、"换个说法"、"再讲一遍"）、一次性请求、当下的情绪、已经过时的信息。
- 克制：只抽取"未来对话仍有价值"的稳定信息；宁可少记，不要过度抽取。

【已有画像（当前已记住的内容）】
{existing}
- 上述已存在的信息，除非用户本轮明确修正或补充，否则不要再次输出。
- 新增 memory 前先对照已有 memories：语义相同（只是措辞不同）的不要新增，宁可不输出。
- 用户明确要求"忘记/删除/不再提"的信息，绝对不要抽取。

【优先级与去重】
- 历史只用于消解代词（他/她/我指代谁），绝不重复抽取历史已含的信息。
- 用户本轮修正或补充的信息要记录，作为对旧记忆的更新。

【敏感信息红线】
- 绝对禁止抽取：联系方式（手机号/邮箱/地址）、银行卡/账户、密码/密钥/token、精确位置、健康状况、政治/宗教立场。命中任一条就直接丢弃该项。

【输出格式】
当前课程 ID：{course_id or '无（普通对话）'}。默认 scope 为 global；只有用户明确说"这门课/本课程"才用 course。
偏好 key 只允许：{', '.join(sorted(_ALLOWED_PREFERENCES))}。
只返回 JSON 数组，不要 Markdown，不要额外说明。每项格式（按需组合）：
{{"action":"set_fact","fact_key":"education_field","fact_value":"计算机专业","category":"background","scope":"global"}}
{{"action":"set_fact","fact_key":"experience_fastapi","fact_value":"用 FastAPI 写过 Web 后端","category":"experience","scope":"global"}}
{{"action":"set_preference","preference_key":"code_example","direction":"pos|neg","scope":"global"}}
{{"action":"add_memory","content":"用一句话自然概括这段有价值的信息","category":"experience|learning_context|goal","scope":"global"}}
若当前消息没有值得长期保存的信息，严格返回 []。

最近对话：
{recent}
当前用户消息：{message[:1200]}"""
        response = get_kb_llm(temperature=0, timeout=20).invoke(prompt)
        return _normalize_ai_intents(_parse_json_payload(_response_text(response)), course_id)
    except Exception:  # noqa: BLE001 - 画像抽取失败不能阻塞回复；None = 走规则 fallback
        logger.info("[chat] semantic memory extraction unavailable", exc_info=True)
        return None


def _extract_and_apply_profile_intents(
    user_id: str, course_id: str, message: str,
    history: List[Dict[str, str]], learner: LearnerModelService,
) -> List[str]:
    """worker 线程：抽取 → 落库（与回复并行；超时场景下自行在后台完成）。

    删除意图不在此处：由 chat() 在提交本任务前同步确定性处理。
    LLM 成功返回 []（无值得保存）时绝不退回正则——正则的误报（如"我会尽快学完"
    → skill:尽快）只在 LLM 不可用时才被接受。
    """
    intents: Optional[List[Dict[str, Any]]]
    if _worth_extracting(message):
        intents = _extract_ai_memory_intents(user_id, message, history, course_id, learner)
    else:
        intents = []
    if intents is None:
        intents = [i for i in extract_memory_intents(message)
                   if i.get("action") != "delete_fact"]
    return apply_memory_intents(user_id, course_id, _merge_memory_intents(intents), learner)


def _merge_memory_intents(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for group in groups:
        for intent in group:
            action = intent.get("action", "")
            if action == "set_preference":
                fingerprint = (action, intent.get("preference_key"), intent.get("direction", "pos"),
                               intent.get("course_id", ""))
            elif action == "set_fact":
                fingerprint = (action, intent.get("fact_key"), str(intent.get("fact_value", "")))
            elif action == "add_memory":
                fingerprint = (action, re.sub(r"\s+", "", str(intent.get("content", "")).lower()),
                               intent.get("course_id", ""))
            else:
                fingerprint = json.dumps(intent, ensure_ascii=False, sort_keys=True)
            if fingerprint not in seen:
                seen.add(fingerprint)
                merged.append(intent)
    return merged


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
                                       course_id=intent.get("course_id", ""))
                applied.append(f"pref:{intent['preference_key']}")
            elif action == "add_memory":
                result = learner.add_memory(user_id, intent["content"],
                                            course_id=intent.get("course_id", ""),
                                            category=intent.get("category", "experience"))
                applied.append(result.get("entity", "memory:updated"))
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
        resolve conversation → 删除意图（确定性） → plan_step 校验 → 加载 PRIOR history
        → 落库当前用户消息 → 事件 → 构建上下文 → LLM(prior history, message)
        ∥ 画像语义抽取（超时转后台） → 落库 AI 回复 → 事件。

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

        # 3) 「忘记/删除」确定性优先：永远不依赖 LLM，且先于一切抽取落库，
        #    保证 worker 里读到的已有画像已不含被删项。
        delete_intents = [i for i in extract_memory_intents(message)
                          if i.get("action") == "delete_fact"]
        applied = apply_memory_intents(user_id, course_id or "", delete_intents, learner)

        # 4) 先加载 PRIOR history（不含当前消息）→ Prompt 中当前消息只出现一次
        history = self._recent_history(conv["conversation_id"], limit=12)

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

        # 6) 上下文（RAG query = step.title + message；真加载持久化 chunks）。
        # 回复和画像抽取并行；回复最多等抽取 _MEMORY_WAIT_SECONDS 秒，
        # 超时后抽取在后台线程自行落库（下一轮生效），绝不阻塞回复返回。
        context_text = self._build_context(user_id, course_id, message, step)
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-llm")
        try:
            reply_future = executor.submit(self._llm_reply, message, context_text, history)
            memory_future = executor.submit(
                _extract_and_apply_profile_intents,
                user_id, course_id or "", message, history, learner,
            )
            reply = reply_future.result()
            try:
                applied.extend(memory_future.result(timeout=_MEMORY_WAIT_SECONDS))
            except (FuturesTimeoutError, TimeoutError):
                logger.info("[chat] profile extraction exceeded %ss; applying in background",
                            _MEMORY_WAIT_SECONDS)
        finally:
            executor.shutdown(wait=False)

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
            try:
                bundle = self._learner.build_bundle(user_id, "")
                ctx = build_chat_context(bundle, self._learner.repo)
                return chat_context_to_prompt(ctx)
            except Exception:  # noqa: BLE001 - 画像失败不影响普通对话
                logger.warning("[chat] build global context degraded: user=%s", user_id, exc_info=True)
                return ""
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
            history_text = "\n".join(
                f"{h['role']}: {h['content'][:2500]}" for h in history[-12:]
            ) or "（无）"
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
