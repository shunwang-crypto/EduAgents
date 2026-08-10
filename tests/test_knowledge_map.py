import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.workflows.study_plan.knowledge_map import build_knowledge_map  # noqa: E402
from edu_agent.workflows.study_plan.schemas import (  # noqa: E402
    DecompositionResult,
    StudentInput,
)


def test_build_knowledge_map_creates_categories_and_path():
    student_input = StudentInput(
        topic="二叉树",
        level="会 Python 基础",
        days=7,
        daily_time="1 小时",
        goal="实现常见遍历",
    )
    decomposition = DecompositionResult(
        prerequisite_concepts=["递归", "栈与队列"],
        core_concepts=["二叉树节点结构", "前中后序遍历"],
        learning_sequence=["递归", "节点结构", "遍历"],
        difficulty_points=["递归调用栈"],
        stage_suggestions=["基础准备", "核心学习", "综合实践"],
        application_directions=["手写三种遍历并验证结果"],
    )

    knowledge_map = build_knowledge_map(student_input, decomposition)

    assert knowledge_map.topic == "二叉树"
    assert len(knowledge_map.nodes) == 5
    assert len(knowledge_map.recommended_path) == len(knowledge_map.nodes)
    assert {node.category for node in knowledge_map.nodes} == {
        "前置知识",
        "核心知识",
        "实践应用",
    }
    assert all(node.learning_objective for node in knowledge_map.nodes)


def test_build_knowledge_map_uses_compact_titles_and_keeps_full_summary():
    long_concept = (
        "系统学习向量数据库的索引构建、相似度检索以及元数据过滤机制，"
        "并完成一个最小检索案例"
    )
    student_input = StudentInput(
        topic="RAG",
        level="会 Python",
        days=5,
        daily_time="45 分钟",
        goal="完成检索问答应用",
    )
    decomposition = DecompositionResult(
        prerequisite_concepts=[],
        core_concepts=[long_concept],
        learning_sequence=[long_concept],
        difficulty_points=[],
        stage_suggestions=["基础准备", "核心学习"],
        application_directions=[],
    )

    node = build_knowledge_map(student_input, decomposition).nodes[0]

    assert len(node.title) <= 24
    assert node.title == "向量数据库的索引构建、相似度检索"
    assert node.summary == long_concept
