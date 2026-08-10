from edu_agent.workflows.kb_qa.workflow import run_kb_qa_workflow
from edu_agent.workflows.plan_chat.schemas import ChatTurn
from edu_agent.workflows.plan_chat.workflow import answer_plan_question
from edu_agent.workflows.study_plan.schemas import StudentInput
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow
from edu_agent.workflows.study_plan.schemas import EvaluatedResource, KnowledgeNode
from edu_agent.workflows.topic_tutor.workflow import run_topic_tutor_workflow


def run_workflow(workflow_name: str, payload: dict) -> dict:
    learner_context = payload.get("learner_context", "")
    adaptive_instructions = payload.get("adaptive_instructions", "")

    if workflow_name == "study_plan":
        return run_study_plan_workflow(
            StudentInput(**payload),
            knowledge_context=payload.get("knowledge_context", "无"),
            learner_context=learner_context,
            adaptive_instructions=adaptive_instructions,
        )

    if workflow_name == "kb_qa":
        return run_kb_qa_workflow(
            question=payload["question"],
            student_input=(
                StudentInput(**payload["student_input"])
                if payload.get("student_input")
                else None
            ),
            learner_context=learner_context,
            adaptive_instructions=adaptive_instructions,
        ).model_dump()

    if workflow_name == "topic_tutor":
        return run_topic_tutor_workflow(
            student_input=StudentInput(**payload["student_input"]),
            knowledge_node=KnowledgeNode(**payload["knowledge_node"]),
            resources=[EvaluatedResource(**item) for item in payload.get("resources", [])],
            learner_context=learner_context,
            adaptive_instructions=adaptive_instructions,
            adaptive_decision_summary=payload.get("adaptive_decision_summary", ""),
        ).model_dump()

    if workflow_name == "plan_chat":
        return answer_plan_question(
            question=payload["question"],
            student_input=StudentInput(**payload["student_input"]),
            final_plan=payload["final_plan"],
            history=[ChatTurn(**item) for item in payload.get("history", [])],
            selected_topic=(
                KnowledgeNode(**payload["selected_topic"])
                if payload.get("selected_topic")
                else None
            ),
            resources=[EvaluatedResource(**item) for item in payload.get("resources", [])],
            learner_context=learner_context,
        ).model_dump()

    raise ValueError(f"Unsupported workflow: {workflow_name}")
