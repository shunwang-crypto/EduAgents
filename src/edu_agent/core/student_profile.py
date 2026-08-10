"""学生画像（Student Profile）：教育智能体个性化的"状态"。

核心设计：
- 水平等级从学生输入的"当前基础"文本**规则推断**（不调 LLM、不信自报下拉框），
  与主项目"摸底诊断不信自报"的哲学一致；
- 画像只负责"状态"，LLM 只负责"按状态调表达"（LLM 不得改写画像数值）；
- 各工作流（问答/计划/辅导）读取画像调整输出深度与粒度。

用法：
    from edu_agent.core.student_profile import build_profile, profile_to_prompt
    profile = build_profile(level_text="零基础但会一点 Python", goal="完成一个报告")
    prompt_context = profile_to_prompt(profile)   # 注入 LLM prompt 的片段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

LEVEL_BEGINNER = "beginner"
LEVEL_INTERMEDIATE = "intermediate"
LEVEL_ADVANCED = "advanced"

LEVEL_LABELS = {
    LEVEL_BEGINNER: "基础",
    LEVEL_INTERMEDIATE: "进阶",
    LEVEL_ADVANCED: "精通",
}

_BEGINNER_HINTS = (
    "零基础", "没有基础", "没学过", "无基础", "完全不懂", "小白",
    "刚入门", "不太会", "不会", "初学", "第一次",
)
_INTERMEDIATE_HINTS = (
    "会", "熟悉", "了解", "学过", "做过", "有一点基础", "基础",
    "能写", "掌握基本", "入门", "有些经验", "会用",
)
_ADVANCED_HINTS = (
    "精通", "熟练", "多年", "资深", "高级", "深入", "专家", "很强",
    "熟练掌握", "长期使用",
)

_STYLE_BY_LEVEL = {
    LEVEL_BEGINNER: (
        "用通俗类比讲解，逐步展开，每一步说明「为什么」；"
        "避免直接抛术语，先建立直觉再给定义。"
    ),
    LEVEL_INTERMEDIATE: (
        "先给结论和关键步骤，再适度展开原理；"
        "补充常见易错点，不要重复基础铺垫。"
    ),
    LEVEL_ADVANCED: (
        "直接给结论与实现要点，深入原理与取舍；"
        "可对比不同方案的优劣，补充进阶延伸与踩坑经验。"
    ),
}


@dataclass
class StudentProfile:
    """教育智能体视角下的学生状态。"""

    level: str = LEVEL_BEGINNER
    level_confidence: float = 0.5
    level_evidence: str = "未提供基础描述"
    goal: str = ""
    known_topics: List[str] = field(default_factory=list)
    weak_topics: List[str] = field(default_factory=list)

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS.get(self.level, self.level)


def infer_level(text: str) -> tuple[str, float, str]:
    """从文本规则推断水平等级，返回 (level, confidence, evidence)。"""
    if not text or not text.strip():
        return LEVEL_BEGINNER, 0.3, "未提供基础描述，默认按基础水平"

    hits: list[tuple[str, float, str]] = []
    for hint in _ADVANCED_HINTS:
        if hint in text:
            hits.append((LEVEL_ADVANCED, 0.85, f"基础描述包含「{hint}」"))
            break
    for hint in _BEGINNER_HINTS:
        if hint in text:
            hits.append((LEVEL_BEGINNER, 0.9, f"基础描述包含「{hint}」"))
            break
    for hint in _INTERMEDIATE_HINTS:
        if hint in text:
            hits.append((LEVEL_INTERMEDIATE, 0.7, f"基础描述包含「{hint}」"))
            break

    if not hits:
        return LEVEL_INTERMEDIATE, 0.4, "未匹配到明确水平词，按进阶水平处理"

    hits.sort(key=lambda item: -item[1])
    level, confidence, evidence = hits[0]
    return level, confidence, evidence


def build_profile(level_text: str = "", goal: str = "") -> StudentProfile:
    """根据基础描述与目标构建画像。"""
    level, confidence, evidence = infer_level(level_text)
    return StudentProfile(
        level=level,
        level_confidence=confidence,
        level_evidence=evidence,
        goal=goal,
    )


def profile_to_prompt(profile: StudentProfile) -> str:
    """把画像转成可注入 LLM prompt 的上下文片段（表达层指令）。"""
    if profile is None:
        return "（暂无学生画像，按通用水平回答）"
    style = _STYLE_BY_LEVEL.get(profile.level, _STYLE_BY_LEVEL[LEVEL_BEGINNER])
    return (
        f"学生水平：{profile.level_label}（{profile.level}）\n"
        f"水平判断依据：{profile.level_evidence}\n"
        f"学习目标：{profile.goal or '未提供'}\n"
        f"表达要求：{style}\n"
        f"若学生水平为「基础」，请避免使用超出其水平的术语而不解释。"
    )
