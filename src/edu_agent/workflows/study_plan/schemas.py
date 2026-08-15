from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

STAGE_COUNT = 3
"""学习计划一级结构固定为 3 个阶段（基础准备 / 核心学习 / 综合应用，标题可自定义）。"""


class StudentInput(BaseModel):
    topic: str = Field(description="学生想学习的内容")
    level: Optional[str] = Field(default=None, description="学生当前基础（可选，首次使用可填，已有画像时不必填）")
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


class LearningStageSuggestion(BaseModel):
    """固定三阶段之一（exactly 3 个）。"""

    stage_id: str = Field(description="阶段稳定标识，如 stage-1/stage-2/stage-3")
    title: str = Field(description="阶段标题（默认：基础准备/核心学习/综合应用，可按主题自定义）")
    objective: str = Field(description="该阶段要达成的目标")
    order: int = Field(ge=1, le=3, description="阶段顺序 1-3")


class DecompositionResult(BaseModel):
    core_concepts: List[str] = Field(description="核心知识点")
    prerequisite_concepts: List[str] = Field(description="前置知识点")
    learning_sequence: List[str] = Field(description="推荐学习顺序")
    difficulty_points: List[str] = Field(description="学习难点")
    stages: List[LearningStageSuggestion] = Field(description="固定 3 个阶段，按 order 1→2→3")
    application_directions: List[str] = Field(description="推荐应用/产出方向（案例、项目等）")

    @model_validator(mode="after")
    def _normalize_stages(self) -> "DecompositionResult":
        """强制 stage order 恰好为 1,2,3（LLM 输出错误时补默认，不抛异常）。"""
        defaults = [
            ("stage-1", "基础准备", "补齐必要背景、前置知识与环境"),
            ("stage-2", "核心学习", "掌握核心概念、方法与原理"),
            ("stage-3", "综合应用", "通过案例、小项目整合知识并总结"),
        ]
        ordered = sorted(self.stages or [], key=lambda s: s.order)
        result: List[LearningStageSuggestion] = []
        for order in range(1, STAGE_COUNT + 1):
            stage = next((s for s in ordered if s.order == order), None)
            if stage is None or not (stage.title or "").strip():
                stage_id, title, objective = defaults[order - 1]
                stage = LearningStageSuggestion(stage_id=stage_id, title=title,
                                                objective=objective, order=order)
            result.append(stage)
        self.stages = result
        return self


class KnowledgeNode(BaseModel):
    id: str = Field(description="知识节点稳定标识（即 kc_id）")
    title: str = Field(description="知识点名称")
    category: str = Field(description="知识点分类")
    parent_id: Optional[str] = Field(default=None, description="父节点标识")
    summary: str = Field(description="知识点摘要")
    prerequisites: List[str] = Field(default_factory=list, description="前置知识点名称")
    difficulty: str = Field(description="难度等级")
    # API 允许最短 1 天 × 5 分钟，同时产品要求固定三个阶段；极小预算下单步可能
    # 少于 10 分钟，因此下限必须允许确定性预算分配，而不是悄悄超出用户时间。
    estimated_minutes: int = Field(ge=1, le=600, description="建议学习时间，单位：分钟")
    stage_id: str = Field(description="所属阶段标识（stage-1/2/3）")
    stage_title: str = Field(description="所属阶段标题")
    stage_order: int = Field(ge=1, le=3, description="所属阶段顺序")
    learning_objective: str = Field(description="可检查的学习目标")


class KnowledgeMap(BaseModel):
    topic: str = Field(description="知识地图主题")
    nodes: List[KnowledgeNode] = Field(description="知识节点列表")
    recommended_path: List[str] = Field(description="推荐学习路径，内容为知识节点 id")


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


class PlanValidationResult(BaseModel):
    passed: bool = Field(description="规则校验是否通过")
    issues: List[str] = Field(description="发现的问题")
    suggestions: List[str] = Field(description="修改建议")
    checked_rules: List[str] = Field(description="已检查的规则")


class ReviewResult(BaseModel):
    review_summary: str = Field(description="对学习计划的检查结果")
    problems_found: List[str] = Field(description="发现的问题")
    final_plan_markdown: str = Field(description="优化后的最终 Markdown 学习计划")
