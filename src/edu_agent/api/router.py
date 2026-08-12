"""FastAPI 路由：课程 / 学习计划 / 普通对话。

user_id 由请求方提供（X-User-Id 头，缺省用配置 DEV_USER_ID）；
Router 只负责取参并转交 Application Services，不组织业务流程。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from edu_agent.application import course_service, study_plan_service
from edu_agent.application import course_category_service, course_source_service
from edu_agent.application.chat_service import ChatService
from edu_agent.config.settings import get_settings

router = APIRouter(prefix="/api")


def _user_id(x_user_id: Optional[str] = Header(default=None)) -> str:
    if x_user_id:
        return x_user_id
    settings = get_settings()
    if settings.learner_model_user_id:
        return settings.learner_model_user_id
    raise HTTPException(status_code=401, detail="missing X-User-Id header")


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
    category_id: Optional[str] = Field(default=None, description="课程分类（可选；必须是当前用户的）")


class UpdateCourseRequest(BaseModel):
    """课程更新（PATCH，字段级）：用 model_fields_set 区分「omitted」与「显式 null」。
    - display_name：重命名（显式 null 不处理）
    - category_id：显式 null = 移动到未分类
    - goal：更新当前课程 Active Goal（唯一 Source of Truth，不新增第二套 Goal 数据）
    """
    display_name: Optional[str] = Field(default=None, description="新的课程名（可选）")
    category_id: Optional[str] = Field(default=None, description="课程分类；显式 null = 移到未分类")
    goal: Optional[str] = Field(default=None, description="学习目标文本（更新 Active Goal）")


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="分类名称")


class RenameCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="新的分类名称")


class GeneratePlanRequest(BaseModel):
    goal: str = Field(default="", description="学习目标（留空沿用课程目标）")
    # 与 CreateCourseRequest 保持一致的范围：先校验，避免非法值跑完整 LLM workflow
    # 最后才在 DB INSERT/UPDATE 因 CHECK 约束失败 → 500。
    duration_days: Optional[int] = Field(default=None, ge=1, le=365, description="学习周期（天）；留空沿用课程已保存默认值")
    daily_minutes: Optional[int] = Field(default=None, ge=5, le=600, description="每天学习分钟；留空沿用课程已保存默认值")
    background: str = Field(default="", description="补充背景（可选，写为 Profile Fact）")


class UpdateStepRequest(BaseModel):
    status: str = Field(description="not_started / in_progress / completed")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000, description="用户消息")
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
            category_id=req.category_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/courses/{course_id}")
def get_course(course_id: str, user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_service.get_course(user_id, course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/courses/{course_id}")
def update_course(course_id: str, req: UpdateCourseRequest,
                  user_id: str = Depends(_user_id)) -> dict:
    """字段级更新：display_name / category_id（显式 null=未分类）/ goal（Active Goal）。"""
    try:
        return course_service.update_course(
            user_id, course_id, fields=set(req.model_fields_set),
            display_name=req.display_name, category_id=req.category_id, goal=req.goal,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: str, user_id: str = Depends(_user_id)) -> None:
    try:
        course_service.delete_course(user_id, course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Course Categories（纯组织层：把用户创建的课程分组；零 Adaptive 语义）
# ---------------------------------------------------------------------------


@router.get("/course-categories")
def list_course_categories(user_id: str = Depends(_user_id)) -> List[dict]:
    return course_category_service.list_categories(user_id)


@router.post("/course-categories")
def create_course_category(req: CreateCategoryRequest,
                           user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_category_service.create_category(user_id, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/course-categories/{category_id}")
def rename_course_category(category_id: str, req: RenameCategoryRequest,
                           user_id: str = Depends(_user_id)) -> dict:
    try:
        return course_category_service.rename_category(user_id, category_id, req.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/course-categories/{category_id}", status_code=204)
def delete_course_category(category_id: str, user_id: str = Depends(_user_id)) -> None:
    """删除分类：分类下课程自动移到未分类（category_id=NULL），课程绝不删除。"""
    try:
        course_category_service.delete_category(user_id, category_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
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


@router.post("/courses/{course_id}/plan/steps/{step_id}/lesson")
def generate_step_lesson(course_id: str, step_id: str,
                         user_id: str = Depends(_user_id)) -> dict:
    """GET-OR-GENERATE 单个 plan step 的讲解（懒生成，首次「开始学习 / 继续学习」调用）。

    已有 lesson_markdown → 直接返回；没有 → LLM 生成并落库。LLM 失败返回 5xx（前端重试），
    不保存错误正文。
    """
    try:
        return study_plan_service.get_or_generate_step_lesson(user_id, course_id, step_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Course Sources（Web / GitHub / Internet Search）
# ---------------------------------------------------------------------------


class AddSourceRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000, description="http/https 链接（Web 或 GitHub）")
    title: str = Field(default="", max_length=300, description="可选显示名；留空自动从 URL 推导")


@router.get("/courses/{course_id}/sources")
def list_course_sources(course_id: str, user_id: str = Depends(_user_id)) -> List[dict]:
    """列出当前用户当前课程的全部资料（含 status / chunk_count）。"""
    try:
        return course_source_service.list_sources(user_id, course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/courses/{course_id}/sources")
def add_course_source(course_id: str, req: AddSourceRequest,
                     user_id: str = Depends(_user_id)) -> dict:
    """新增（或重试 failed）一个课程资料：Web 抓取 / GitHub 导入。

    事务外做外部导入；失败 status=failed + 简短可读错误，不泄露内部细节。
    重复 URL 复用同一 source_id（replace 语义）。
    """
    try:
        return course_source_service.add_source(user_id, course_id, req.url, title=req.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/courses/{course_id}/sources/{source_id}", status_code=204)
def delete_course_source(course_id: str, source_id: str,
                         user_id: str = Depends(_user_id)) -> None:
    """删除资料：清 chunks + course_sources 行（ownership 优先）。"""
    try:
        course_source_service.delete_source(user_id, course_id, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/courses/{course_id}/sources/search")
def search_course_sources(course_id: str, q: str = Query("", min_length=1, max_length=300),
                          limit: int = Query(5, ge=1, le=8),
                          user_id: str = Depends(_user_id)) -> List[Dict[str, str]]:
    """搜索互联网资料候选（不直接导入）。课程必须存在（X-User-Id + course scoped）。"""
    try:
        return course_source_service.search_sources(user_id, course_id, q, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    course_id: Optional[str] = Field(default=None, description="课程（可为空=普通对话）")


@router.post("/chat/conversations")
def create_conversation(req: CreateConversationRequest, user_id: str = Depends(_user_id),
                        service: ChatService = Depends(_chat_service)) -> dict:
    """「新对话」：真正创建新 conversation（不再复用已有主会话）。"""
    try:
        return service.create_conversation(user_id, req.course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/chat")
def chat(req: ChatRequest, user_id: str = Depends(_user_id),
         service: ChatService = Depends(_chat_service)) -> dict:
    try:
        return service.chat(
            user_id=user_id,
            message=req.message,
            course_id=req.course_id,
            conversation_id=req.conversation_id,
            plan_step_id=req.plan_step_id,
        )
    except KeyError as exc:
        # conversation / course ownership 错误：404（信息隐藏）
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/chat")
def get_chat(course_id: Optional[str] = None, conversation_id: Optional[str] = None,
             user_id: str = Depends(_user_id),
             service: ChatService = Depends(_chat_service)) -> dict:
    try:
        return service.get_conversation(user_id, course_id=course_id, conversation_id=conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/chat/conversations")
def list_conversations(course_id: Optional[str] = None, limit: int = Query(6, ge=1, le=20),
                       user_id: str = Depends(_user_id),
                       service: ChatService = Depends(_chat_service)) -> List[dict]:
    """最近对话列表：course_id 为空 = General；否则该 Course 的对话。

    title 已由后端做 COALESCE（旧 title=NULL fallback 首条 user 消息）；
    空对话（无 user 消息）已排除。前端按 updated_at DESC 展示。
    """
    try:
        return service.list_conversations(user_id, course_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
