from typing import List, Literal, Optional

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


class ConceptSpec(BaseModel):
    """一次 decomposition 内的结构化知识点（最终 canonical KC 的来源）。

    temp_id：只在本次 decomposition 内用于建立 prerequisite_refs 引用；
    它不是最终 canonical KC ID（canonicalization 负责 temp_id → canonical kc_id）。
    """

    temp_id: str = Field(description="本次分解内唯一临时标识，如 numpy / linear_algebra")
    title: str = Field(description="知识点人类可读标题")
    summary: str = Field(default="", description="知识点摘要")
    learning_objective: str = Field(default="", description="可观察的学习目标（非模板化）")
    category: Literal["prerequisite", "core", "target", "application"] = Field(
        default="core", description="知识点分类"
    )
    content_type: Literal["theory", "code", "mixed"] = Field(
        default="mixed", description="内容类型"
    )
    difficulty: str = Field(default="intermediate", description="难度（beginner/intermediate/advanced）")
    stage_order: int = Field(ge=1, le=3, default=1, description="所属阶段（仅分组/展示/调度）")
    prerequisite_refs: List[str] = Field(
        default_factory=list, description="前置知识点 temp_id 列表（只能引用本次 concepts 中已有的 temp_id）"
    )
    is_target: bool = Field(default=False, description="是否是对应学习目标的真正目标知识点")
    estimated_minutes: Optional[int] = Field(default=None, description="建议学习时间（分钟，可空）")


class DecompositionResult(BaseModel):
    # 新生产流程只使用 concepts（显式 prerequisite_refs 决定 graph edge）。
    # 旧字段仅保留 compatibility（legacy test / API），不再作为 Graph source of truth。
    concepts: List[ConceptSpec] = Field(default_factory=list, description="结构化知识点（唯一 Graph source of truth）")
    target_refs: List[str] = Field(default_factory=list, description="真正目标知识点 temp_id 列表")
    core_concepts: List[str] = Field(default_factory=list, description="（compatibility）核心知识点")
    prerequisite_concepts: List[str] = Field(default_factory=list, description="（compatibility）前置知识点")
    learning_sequence: List[str] = Field(default_factory=list, description="（compatibility）推荐学习顺序")
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

    @model_validator(mode="after")
    def _normalize_concepts(self) -> "DecompositionResult":
        """compatibility：旧字段填充 concepts（当 concepts 为空时）。

        仅当生产流程未提供结构化 concepts 时才从旧字段合成，保证 legacy
        test / 调用方仍可得到可构建的 graph。

        Compatibility fallback derives a conservative sparse prerequisite chain
        from legacy learning_sequence when explicit ConceptSpec relations are
        unavailable. 每个节点最多只依赖学习顺序中的前一个节点（A→B→C→D），
        不产生 complete-bipartite dense graph，也不依赖 Stage 分组。
        """
        if self.concepts:
            # 确保 target_refs 与 is_target 一致性
            if not self.target_refs:
                self.target_refs = [c.temp_id for c in self.concepts if c.is_target]
            return self

        def _dedup(items) -> List[str]:
            seen: set = set()
            out: List[str] = []
            for x in items or []:
                key = (x or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    out.append(key)
            return out

        # 1) 概念全集 = prereq ∪ core ∪ application（旧 behavior 的节点来源）。
        #    learning_sequence 提供顺序 hint：仅保留能精确匹配某个概念的项，
        #    其余（缩写/句子式 hint）丢弃，避免产生多余/语义重复节点。
        prereq_list = _dedup(self.prerequisite_concepts)
        core_list = _dedup(self.core_concepts)
        app_list = _dedup(self.application_directions)
        concept_pool = prereq_list + core_list + app_list
        pool_set = set(concept_pool)

        ordered: List[str] = []
        seen: set = set()
        for title in _dedup(self.learning_sequence):
            if title in pool_set and title not in seen:
                ordered.append(title)
                seen.add(title)
        for title in concept_pool:
            if title not in seen:
                ordered.append(title)
                seen.add(title)
        if not ordered:
            self.concepts = []
            return self

        # 2) 分类映射：title → (category, stage, difficulty)
        prereq_set = set(prereq_list)
        app_set = set(app_list)

        def _meta(title):
            if title in prereq_set:
                return ("prerequisite", 1, "beginner")
            if title in app_set:
                return ("application", 3, "advanced")
            return ("core", 2, "intermediate")

        synthesized: List[ConceptSpec] = []
        # 每个节点最多依赖前一个序列节点（sparse conservative chain）。
        prev_temp: Optional[str] = None
        for title in ordered:
            category, stage, difficulty = _meta(title)
            refs = [prev_temp] if prev_temp is not None else []
            synthesized.append(ConceptSpec(
                temp_id=_slugify(title), title=title, summary=title, category=category,
                content_type="mixed", difficulty=difficulty, stage_order=stage,
                prerequisite_refs=refs, is_target=False,
            ))
            prev_temp = _slugify(title)
        # 3) target fallback：优先 target_refs/is_target；缺省 sequence 末节点。
        self.concepts = synthesized
        target_refs = _dedup(self.target_refs)
        if not target_refs:
            target_refs = [synthesized[-1].temp_id]
        # 标记 is_target（保持与 target_refs 一致）。
        target_set = set(target_refs)
        for c in synthesized:
            if c.temp_id in target_set:
                c.is_target = True
        self.target_refs = target_refs
        return self


def _slugify(value: str) -> str:
    """把人类标题派生为稳定临时 id（仅 legacy 合成用）。"""
    import re
    norm = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", value or "").strip("_")
    if not norm:
        norm = "concept"
    return norm.lower()


class KnowledgeNode(BaseModel):
    id: str = Field(description="知识节点稳定标识（canonical KC ID，如 embedding / numpy_array）")
    title: str = Field(description="知识点名称")
    category: str = Field(description="知识点分类")
    canonical_key: Optional[str] = Field(
        default=None,
        description="LLM 草稿阶段提供的可选规范化键；若合法则作为 canonical ID 候选，否则按标题派生",
    )
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
