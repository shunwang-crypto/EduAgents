import re
from urllib.parse import urlparse

from edu_agent.workflows.study_plan.schemas import (
    DecompositionResult,
    EvaluatedResource,
    ResearchResult,
    WebResource,
)


OFFICIAL_HINTS = (
    "docs.",
    "developer.",
    "learn.",
    "documentation",
    "doc",
    "官方",
    "文档",
)
COURSE_HINTS = ("course", "课程", "university", "mit", "stanford", "edu", "coursera", "edx")
PROJECT_HINTS = ("github", "gitlab", "kaggle", "project", "项目", "实战", "案例")
TUTORIAL_HINTS = ("tutorial", "guide", "入门", "教程", "quickstart", "指南")
BLOG_HINTS = ("blog", "medium", "csdn", "zhihu", "juejin", "博客", "专栏")
LOW_QUALITY_HINTS = ("广告", "下载站", "聚合", "采集", "转载", "培训报名", "优惠")


def _combined_text(resource: WebResource) -> str:
    return f"{resource.title} {resource.url} {resource.summary}".lower()


def _clamp_score(value: int) -> int:
    return max(1, min(5, value))


def _extract_terms(text: str) -> set[str]:
    terms = re.findall(r"[A-Za-z0-9_+#.-]{2,}|[\u4e00-\u9fff]{2,}", text)
    return {term.lower() for term in terms if len(term.strip()) >= 2}


def _decomposition_terms(decomposition: DecompositionResult) -> set[str]:
    items = (
        decomposition.core_concepts
        + decomposition.prerequisite_concepts
        + decomposition.learning_sequence
        + decomposition.application_directions
    )
    terms: set[str] = set()
    for item in items:
        terms.update(_extract_terms(item))
    return terms


def classify_source_type(resource: WebResource) -> str:
    text = _combined_text(resource)
    domain = urlparse(resource.url).netloc.lower()

    if any(hint in text or hint in domain for hint in OFFICIAL_HINTS):
        return "official_doc"
    if any(hint in text or hint in domain for hint in PROJECT_HINTS):
        return "project"
    if any(hint in text or hint in domain for hint in COURSE_HINTS):
        return "course"
    if any(hint in text or hint in domain for hint in TUTORIAL_HINTS):
        return "tutorial"
    if any(hint in text or hint in domain for hint in BLOG_HINTS):
        return "blog"
    return "unknown"


def resource_matches_terms(resource: WebResource | EvaluatedResource, terms: set[str]) -> bool:
    if not terms:
        return True
    text = f"{resource.title} {resource.summary} {resource.url}".lower()
    return any(term in text for term in terms)


def resources_look_relevant(
    topic: str,
    resources: list[WebResource] | list[EvaluatedResource],
) -> bool:
    terms = _extract_terms(topic)
    if not resources:
        return False
    return any(resource_matches_terms(resource, terms) for resource in resources)


def evaluate_resource_locally(
    resource: WebResource,
    decomposition: DecompositionResult,
) -> EvaluatedResource:
    source_type = classify_source_type(resource)
    terms = _decomposition_terms(decomposition)
    relevant = resource_matches_terms(resource, terms)
    text = _combined_text(resource)

    score = 3 if relevant else 2
    if source_type == "official_doc":
        score += 2
    elif source_type in {"course", "project", "tutorial"}:
        score += 1
    elif source_type == "blog":
        score -= 1
    if any(hint in text for hint in LOW_QUALITY_HINTS):
        score -= 2

    score = _clamp_score(score)
    if not relevant:
        reason = "与拆解出的核心知识点匹配较弱，建议只作为补充参考。"
    elif source_type == "official_doc":
        reason = "与学习主题相关，且来源接近官方文档，适合查证概念和 API。"
    elif source_type == "course":
        reason = "与学习主题相关，课程型内容适合系统学习。"
    elif source_type == "project":
        reason = "与学习主题相关，适合用于实践或综合产出。"
    elif source_type == "tutorial":
        reason = "与学习主题相关，教程型内容适合入门跟练。"
    elif source_type == "blog":
        reason = "与学习主题有一定相关性，但博客质量差异较大，建议交叉验证。"
    else:
        reason = "与学习主题有一定相关性，但来源类型不明确，建议谨慎使用。"

    stage_by_type = {
        "official_doc": "概念查证与中后期对照",
        "course": "基础到系统学习阶段",
        "project": "实践阶段或最终项目",
        "tutorial": "入门阶段",
        "blog": "补充阅读",
        "unknown": "按需补充",
    }

    return EvaluatedResource(
        title=resource.title,
        url=resource.url,
        summary=resource.summary,
        source_type=source_type,
        quality_score=score,
        reason=reason,
        suitable_stage=stage_by_type[source_type],
    )


def evaluate_resources_locally(
    research: ResearchResult,
    decomposition: DecompositionResult,
) -> list[EvaluatedResource]:
    resources = [
        evaluate_resource_locally(resource, decomposition)
        for resource in research.resources
    ]
    return sorted(
        resources,
        key=lambda resource: (resource.quality_score, resource.source_type == "official_doc"),
        reverse=True,
    )
