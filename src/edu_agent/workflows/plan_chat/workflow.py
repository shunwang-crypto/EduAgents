import json
from typing import List

from edu_agent.core.agent_runner import invoke_structured_output
from edu_agent.core.llm import get_llm
from edu_agent.tools.web_search import web_search
from edu_agent.workflows.plan_chat.prompts import PLAN_CHAT_PROMPT
from edu_agent.workflows.plan_chat.schemas import ChatTurn, PlanChatAnswer
from edu_agent.workflows.study_plan.schemas import (
    EvaluatedResource,
    KnowledgeNode,
    StudentInput,
)


SEARCH_HINTS = ("最新", "官方", "文档", "资料", "搜索", "查一下", "版本", "API")


def _needs_search(question: str) -> bool:
    return any(hint.lower() in question.lower() for hint in SEARCH_HINTS)


def _fallback_answer(question: str, reason: Exception) -> PlanChatAnswer:
    return PlanChatAnswer(
        intent="fallback",
        answer_markdown=(
            f"暂时无法完成模型回答。你可以先依据当前学习计划拆解问题：\n\n"
            f"1. 明确问题中的具体知识点；\n2. 对照计划中的学习任务和检查方式；\n"
            f"3. 完成一个最小练习并记录结果。\n\n问题：{question}\n\n原因：{reason}"
        ),
        citations=[],
        suggested_questions=["这个问题对应计划中的哪一天？", "给我一个最小练习。", "如何检查我是否学会？"],
        plan_change_suggested=False,
    )


def answer_plan_question(
    question: str,
    student_input: StudentInput,
    final_plan: str,
    history: List[ChatTurn] | None = None,
    selected_topic: KnowledgeNode | None = None,
    resources: List[EvaluatedResource] | None = None,
) -> PlanChatAnswer:
    history = history or []
    resources = resources or []
    external_resources: list[dict] = []

    if _needs_search(question):
        query = f"{selected_topic.title} {question}" if selected_topic else question
        search_result = web_search(query, max_results=3)
        external_resources = [item.model_dump() for item in search_result["results"]]

    resource_payload = [resource.model_dump() for resource in resources[:5]] + external_resources
    known_urls = {
        item.get("url")
        for item in resource_payload
        if isinstance(item, dict) and item.get("url")
    }

    try:
        result = invoke_structured_output(
            PLAN_CHAT_PROMPT,
            PlanChatAnswer,
            {
                "student_input": json.dumps(
                    student_input.model_dump(), ensure_ascii=False, indent=2
                ),
                "selected_topic": json.dumps(
                    selected_topic.model_dump(), ensure_ascii=False, indent=2
                )
                if selected_topic
                else "未选择具体知识点。",
                "final_plan": final_plan[:14000],
                "history": json.dumps(
                    [turn.model_dump() for turn in history[-8:]],
                    ensure_ascii=False,
                    indent=2,
                ),
                "resources": json.dumps(
                    resource_payload, ensure_ascii=False, indent=2
                ),
                "question": question,
            },
            get_llm(temperature=0.3),
        )
        result.citations = [url for url in result.citations if url in known_urls]
        return result
    except Exception as exc:  # noqa: BLE001 - chat should always return a displayable response
        return _fallback_answer(question, exc)

