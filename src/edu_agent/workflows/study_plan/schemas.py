from typing import List

from pydantic import BaseModel, Field


class StudentInput(BaseModel):
    topic: str = Field(description="学生想学习的内容")
    level: str = Field(description="学生当前基础")
    days: int = Field(description="学习周期，单位：天")
    daily_time: str = Field(description="每天可投入学习时间")
    goal: str = Field(description="学生学习目标")


class AnalysisResult(BaseModel):
    topic: str = Field(description="整理后的学习主题")
    level_summary: str = Field(description="对学生当前基础的分析")
    goal_summary: str = Field(description="对学习目标的整理")
    prerequisites: List[str] = Field(description="需要补充的前置知识")
    need_web_search: bool = Field(description="是否需要联网搜索")
    search_queries: List[str] = Field(description="推荐搜索关键词")


class WebResource(BaseModel):
    title: str = Field(description="资源标题")
    url: str = Field(description="资源链接")
    summary: str = Field(description="资源摘要")


class ResearchResult(BaseModel):
    search_enabled: bool = Field(description="是否启用了联网搜索")
    summary: str = Field(description="搜索结果整体摘要")
    key_points: List[str] = Field(description="搜索得到的关键知识点")
    resources: List[WebResource] = Field(description="推荐资源列表")


class DecompositionResult(BaseModel):
    core_concepts: List[str] = Field(description="核心知识点")
    prerequisite_concepts: List[str] = Field(description="前置知识点")
    learning_sequence: List[str] = Field(description="推荐学习顺序")
    difficulty_points: List[str] = Field(description="学习难点")
    stage_suggestions: List[str] = Field(description="阶段划分建议")
    practice_directions: List[str] = Field(description="推荐实践方向")


class EvaluatedResource(BaseModel):
    title: str = Field(description="资源标题")
    url: str = Field(description="资源链接")
    summary: str = Field(description="资源摘要")
    source_type: str = Field(
        description="资源类型，建议取 official_doc / tutorial / course / project / blog / unknown"
    )
    quality_score: int = Field(ge=1, le=5, description="资源质量评分，1 到 5 分")
    reason: str = Field(description="推荐或降权原因")
    suitable_stage: str = Field(description="适合的学习阶段")


class EvaluatedResearchResult(BaseModel):
    search_enabled: bool = Field(description="是否启用了联网搜索")
    summary: str = Field(description="资源质量评估摘要")
    key_points: List[str] = Field(description="筛选后保留的关键知识点")
    resources: List[EvaluatedResource] = Field(description="质量评估后的资源列表")


class DraftPlan(BaseModel):
    plan_markdown: str = Field(description="初版 Markdown 学习计划")


class PracticePlan(BaseModel):
    practice_summary: str = Field(description="练习设计摘要")
    daily_practice_tasks: List[str] = Field(description="每日练习任务")
    stage_check_tasks: List[str] = Field(description="阶段检查任务")
    final_project: str = Field(description="最终项目或综合任务")
    reflection_questions: List[str] = Field(description="复盘反思问题")


class PlanValidationResult(BaseModel):
    passed: bool = Field(description="规则校验是否通过")
    issues: List[str] = Field(description="发现的问题")
    suggestions: List[str] = Field(description="修改建议")
    checked_rules: List[str] = Field(description="已检查的规则")


class ReviewResult(BaseModel):
    review_summary: str = Field(description="对学习计划的检查结果")
    problems_found: List[str] = Field(description="发现的问题")
    final_plan_markdown: str = Field(description="优化后的最终 Markdown 学习计划")
