"""FastAPI 路由：课程 / 学习计划 / 普通对话。

user_id 由请求方提供（X-User-Id 头，缺省用配置 DEV_USER_ID）；
Router 只负责取参并转交 Application Services，不组织业务流程。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from edu_agent.application import course_service, study_plan_service
from edu_agent.application.chat_service import ChatService
from edu_agent.config.settings import get_settings

router = APIRouter(prefix="/api")


def _user_id(x_user_id: Optional[str] = Header(default=None)) -> str:
    if x_user_id:
        return x_user_id
    settings = get_settings()
    return settings.learner_model_user_id


def _chat_service() -> ChatService:
    return ChatService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateCourseRequest(BaseModel):
    topic: str = Field(description="想学习的内容/课程名")
    goal: str = Field(default="", description="学习目标（可选）")
    duration_days: int = Field(default=14, ge=1, le=365)
    daily_minutes: int = Field(default=60, ge=5, le=600)


class UpdateCourseRequest(BaseModel):
    title: str = Field(description="新的课程名")


class GeneratePlanRequest(BaseModel):
    goal: str = Field(default="", description="学习目标（留空沿用课程目标）")
    duration_days: int = Field(default=14, ge=1, le=365)
    daily_minutes: int = Field(default=60, ge=5, le=600)
    background: str = Field(default="", description="补充背景（可选，写为 Profile Fact）")
    extra_requirement: str = Field(default="", description="本次特殊要求（可选）")


class UpdateStepRequest(BaseModel):
    status: str = Field(description="not_started / in_progress / completed")


class ChatRequest(BaseModel):
    message: str = Field(description="用户消息")
    course_id: Optional[str] = Field(default=None, description="当前课程（无课程为普通对话）")
    conversation_id: Optional[str] = Field(default=None)
    plan_step_id: Optional[str] = Field(default=None, description="当前计划步骤（就此提问进入，可空）")


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


@router.get("/courses")
def list_courses(user_id: str = Depends(_user_id)) -> List[dict]:
    return course_service.list_courses(user_id)


@router.post("/courses")
def create_course(req: CreateCourseRequest, user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_service.create_course(
            user_id, req.topic, goal=req.goal,
            duration_days=req.duration_days, daily_minutes=req.daily_minutes,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/courses/{course_id}")
def get_course(course_id: str, user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_service.get_course(user_id, course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/courses/{course_id}")
def rename_course(course_id: str, req: UpdateCourseRequest,
                  user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_service.rename_course(user_id, course_id, req.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: str, user_id: str = Depends(_user_id)) -> None:
    course_service.delete_course(user_id, course_id)


# ---------------------------------------------------------------------------
# Study Plan
# ---------------------------------------------------------------------------


@router.post("/courses/{course_id}/plan/generate")
def generate_plan(course_id: str, req: GeneratePlanRequest,
                  user_id: str = Depends(_user_id)) -> dict:
    try:
        return study_plan_service.generate_plan(
            user_id, course_id, goal=req.goal,
            duration_days=req.duration_days, daily_minutes=req.daily_minutes,
            optional_background=req.background,
            optional_extra_requirement=req.extra_requirement,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/courses/{course_id}/plan")
def get_plan(course_id: str, user_id: str = Depends(_user_id)) -> dict:
    plan = study_plan_service.get_plan(user_id, course_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="no plan for course")
    return plan


@router.patch("/courses/{course_id}/plan/steps/{step_id}")
def update_step(course_id: str, step_id: str, req: UpdateStepRequest,
                user_id: str = Depends(_user_id)) -> dict:
    try:
        return study_plan_service.update_step_status(user_id, course_id, step_id, req.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/courses/{course_id}/plan/steps/{step_id}")
def get_step(course_id: str, step_id: str, user_id: str = Depends(_user_id)) -> dict:
    """取单个计划步骤（校验属于 user+course；供 Chat「就此提问」上下文）。"""
    try:
        return study_plan_service.get_step(user_id, course_id, step_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@router.post("/chat")
def chat(req: ChatRequest, user_id: str = Depends(_user_id),
         service: ChatService = Depends(_chat_service)) -> dict:
    return service.chat(
        user_id=user_id,
        message=req.message,
        course_id=req.course_id,
        conversation_id=req.conversation_id,
        plan_step_id=req.plan_step_id,
    )


@router.get("/chat")
def get_chat(course_id: Optional[str] = None, conversation_id: Optional[str] = None,
             user_id: str = Depends(_user_id),
             service: ChatService = Depends(_chat_service)) -> dict:
    return service.get_conversation(user_id, course_id=course_id, conversation_id=conversation_id)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
