from edu_agent.workflows.study_plan.schemas import StudentInput
from edu_agent.workflows.study_plan.workflow import run_study_plan_workflow


def run_workflow(workflow_name: str, payload: dict) -> dict:
    if workflow_name == "study_plan":
        return run_study_plan_workflow(StudentInput(**payload))

    raise ValueError(f"Unsupported workflow: {workflow_name}")

