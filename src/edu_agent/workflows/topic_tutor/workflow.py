import json
from typing import List

from edu_agent.core.agent_runner import invoke_structured_output
from edu_agent.core.llm import get_llm
from edu_agent.workflows.study_plan.schemas import (
    EvaluatedResource,
    KnowledgeNode,
    StudentInput,
)
from edu_agent.workflows.topic_tutor.prompts import TOPIC_TUTOR_PROMPT
from edu_agent.workflows.topic_tutor.schemas import TopicDetail


def _fallback_topic_detail(node: KnowledgeNode, reason: Exception) -> TopicDetail:
    return TopicDetail(
        title=node.title,
        learning_objective=node.learning_objective,
        explanation_markdown=(
            f"### {node.title}\n\n{node.summary}\n\n"
            f"建议先确认这些前置知识：{', '.join(node.prerequisites) or '无额外前置知识'}。"
        ),
        example_markdown=f"围绕「{node.title}」完成以下实践：{node.practice_task}",
        common_mistakes=["只记结论，没有验证关键步骤。", f"专题讲解使用降级内容，原因：{reason}"],
        exercises=[node.practice_task],
        completion_checks=[node.check_method],
        suggested_questions=[
            f"给我再举一个「{node.title}」的例子。",
            f"「{node.title}」和前置知识有什么关系？",
            f"针对「{node.title}」生成 3 道练习。",
        ],
        resource_urls=[],
    )


def run_topic_tutor_workflow(
    student_input: StudentInput,
    knowledge_node: KnowledgeNode,
    resources: List[EvaluatedResource] | None = None,
) -> TopicDetail:
    resources = resources or []
    known_urls = {resource.url for resource in resources if resource.url}

    try:
        result = invoke_structured_output(
            TOPIC_TUTOR_PROMPT,
            TopicDetail,
            {
                "student_input": json.dumps(
                    student_input.model_dump(), ensure_ascii=False, indent=2
                ),
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
        return result
    except Exception as exc:  # noqa: BLE001 - focused tutoring should degrade gracefully
        return _fallback_topic_detail(knowledge_node, exc)

