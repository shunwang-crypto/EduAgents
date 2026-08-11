"""反向契约测试：生产代码/提示词不得重新引入练习系统语义。

允许的例外：禁止性文案（"禁止生成练习题"）、validator 黑名单词
（用于检查计划里不能出现空泛表达）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# 业务实现级关键词（出现即视为练习系统复活）
_BUSINESS_MARKERS = [
    "PracticeDesigner",
    "QuestionBank",
    "quiz_generation",
    "mistake_reflection",
    "automatic_grading",
    "answer_submission",
    "错题本",
    "题库",
    "自动判题",
    "答案提交",
    "正确率",
    "开始练习",
    "做题",
    "答题",
    "刷题",
    "测试题",
    "练习题",
    "mastery +=",
    "mastery -=",
]

# 允许出现的"禁止性"上下文（含这些词的行若为禁止/反例，则不判定为业务实现）
_ALLOWED_NEGATION = ("禁止", "不允许", "不要", "不是", "不得", "不能", "黑名单", "反例", "反模式", "避免")


def _iter_py_files():
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in str(p)]


@pytest.mark.parametrize("marker", _BUSINESS_MARKERS)
def test_no_exercise_generation(marker):
    """全项目生产代码不得出现练习系统实现关键词（禁止性文案除外）。"""
    hits = []
    for path in _iter_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if marker in line:
                # 禁止/反例上下文放行
                if any(neg in line for neg in _ALLOWED_NEGATION):
                    continue
                hits.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert hits == [], f"练习系统关键词出现于生产代码:\n" + "\n".join(hits)


def test_no_streamlit_and_no_legacy_partner():
    """Streamlit 与旧 Partner 画像架构不得回归。"""
    hits = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        for marker in ("streamlit", "LearnerStateProvider", "remote_provider", "killoppen"):
            if marker in text:
                hits.append(f"{path.relative_to(SRC)}: {marker}")
    assert hits == [], "\n".join(hits)


def test_plan_prompt_forbids_exercises():
    """生成计划提示词必须明确禁止练习题。"""
    prompts = (SRC / "edu_agent" / "workflows" / "study_plan" / "prompts.py").read_text(encoding="utf-8")
    assert "禁止生成练习题" in prompts or "不允许练习题" in prompts
    assert "禁止生成练习题、测试题、测验" in prompts


def test_plan_steps_schema_has_stage_fields():
    """plan_steps 表必须包含三阶段与 KC 信息。"""
    db = (SRC / "edu_agent" / "learner_model" / "db.py").read_text(encoding="utf-8")
    for field in ("stage_id", "stage_title", "stage_order", "kc_id", "learning_objective", "prerequisites_json", "difficulty"):
        assert field in db, f"plan_steps 缺字段: {field}"
