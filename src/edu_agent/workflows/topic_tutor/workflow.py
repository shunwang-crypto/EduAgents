import json
from typing import List, Optional

from edu_agent.core.agent_runner import invoke_structured_output
from edu_agent.core.llm import get_llm
from edu_agent.workflows.study_plan.schemas import (
    EvaluatedResource,
    KnowledgeNode,
    StudentInput,
)
from edu_agent.workflows.topic_tutor.prompts import TOPIC_TUTOR_PROMPT
from edu_agent.workflows.topic_tutor.schemas import TopicDetail


def _fallback_topic_detail(
    node: KnowledgeNode,
    reason: Exception,
    learner_context: str = "",
    adaptive_instructions: str = "",
) -> TopicDetail:
    prereq_hint = ", ".join(node.prerequisites) or "无额外前置知识"
    return TopicDetail(
        title=node.title,
        learning_objective=node.learning_objective,
        explanation_markdown=(
            f"### {node.title}\n\n{node.summary}\n\n"
            f"建议先确认这些前置知识：{prereq_hint}。"
        ),
        example_markdown=f"围绕「{node.title}」完成以下实践：{node.practice_task}",
        common_mistakes=["只记结论，没有验证关键步骤。", f"专题讲解使用降级内容，原因：{reason}"],
        completion_checks=[node.check_method],
        next_learning_suggestions=[
            f"继续学习与「{node.title}」关联的后续知识点。",
            f"若前置知识不足，先补充：{prereq_hint}。",
        ],
        suggested_questions=[
            f"给我再举一个「{node.title}」的例子。",
            f"「{node.title}」和前置知识有什么关系？",
            f"「{node.title}」有什么易错点？",
        ],
        resource_urls=[],
    )


def run_topic_tutor_workflow(
    student_input: StudentInput,
    knowledge_node: KnowledgeNode,
    resources: Optional[List[EvaluatedResource]] = None,
    learner_context: str = "",
    adaptive_instructions: str = "",
    adaptive_decision_summary: str = "",
) -> TopicDetail:
    resources = resources or []
    known_urls = {resource.url for resource in resources if resource.url}

    try:
        result = invoke_structured_output(
            TOPIC_TUTOR_PROMPT,
            TopicDetail,
            {
                "learner_context": learner_context or "（暂无学习者上下文，按通用水平讲解）",
                "adaptive_instructions": adaptive_instructions or "循序渐进讲解，不生成练习。",
                "knowledge_node": json.dumps(
                    knowledge_node.model_dump(), ensure_ascii=False, indent=2
                ),
                "resources": json.dumps(
                    [resource.model_dump() for resource in resources[:5]],
                    ensure_ascii=False,
                    indent=2,
                ),
            },
            get_llm(temperature=0.25),
        )
        result.resource_urls = [url for url in result.resource_urls if url in known_urls]
        result.adaptive_decision_summary = adaptive_decision_summary
        return result
    except Exception as exc:  # noqa: BLE001 - focused tutoring should degrade gracefully
        result = _fallback_topic_detail(
            knowledge_node, exc, learner_context, adaptive_instructions
        )
        result.adaptive_decision_summary = adaptive_decision_summary
        return result
