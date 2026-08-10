"""MockLearnerStateProvider：合作伙伴服务未启动时的开发/测试/演示数据。

数据来自当前已知 Java 实训场景：
- 掌握度：CLASS .90 / EXCEPTION .50 / IO .33 / POLYMORPHISM .24 /
         INHERITANCE .17 / ENCAPSULATION .00 / COLLECTION .00
- 六维能力：understanding .30 / application .31 / reasoning .32 /
           expression .30 / reflection .30 / transfer .21
- 偏好：example_driven（worked_example 0.82 / 14 样本）、visual .30、reading .35
- 进度：progress = .31
"""

from __future__ import annotations

from edu_agent.integrations.learner_state.adapter import make_mock_course_state, parse_global_state
from edu_agent.integrations.learner_state.provider import LearnerStateProvider
from edu_agent.integrations.learner_state.schemas import CourseLearnerState, GlobalLearnerState, Goal

DEFAULT_USER_ID = "STU-001"
DEFAULT_COURSE_ID = "JAVA-OOP"
DEFAULT_GOAL_ID = "GOAL-JAVA-001"

# Java OOP 课程知识掌握度（课程级）
JAVA_KNOWLEDGE = [
    {"kc_id": "CLASS", "name": "类与对象", "mastery": 0.90, "confidence": 0.92,
     "status": "mastered", "trend": "stable", "evidence_count": 12},
    {"kc_id": "EXCEPTION", "name": "异常处理", "mastery": 0.50, "confidence": 0.70,
     "status": "learning", "trend": "improving", "evidence_count": 6},
    {"kc_id": "IO", "name": "文件与流", "mastery": 0.33, "confidence": 0.55,
     "status": "weak", "trend": "improving", "evidence_count": 4},
    {"kc_id": "POLYMORPHISM", "name": "多态", "mastery": 0.24, "confidence": 0.78,
     "status": "weak", "trend": "improving", "evidence_count": 8},
    {"kc_id": "INHERITANCE", "name": "继承", "mastery": 0.17, "confidence": 0.60,
     "status": "weak", "trend": "improving", "evidence_count": 5},
    {"kc_id": "ENCAPSULATION", "name": "封装", "mastery": 0.00, "confidence": 0.20,
     "status": "unknown", "trend": "unknown", "evidence_count": 0},
    {"kc_id": "COLLECTION", "name": "集合框架", "mastery": 0.00, "confidence": 0.10,
     "status": "unknown", "trend": "unknown", "evidence_count": 0},
]

JAVA_ABILITIES = {
    "understanding": {"score": 0.30, "confidence": 0.72, "trend": "stable", "evidence_count": 12},
    "application": {"score": 0.31, "confidence": 0.70, "trend": "stable", "evidence_count": 11},
    "reasoning": {"score": 0.32, "confidence": 0.68, "trend": "stable", "evidence_count": 10},
    "expression": {"score": 0.30, "confidence": 0.65, "trend": "stable", "evidence_count": 9},
    "reflection": {"score": 0.30, "confidence": 0.60, "trend": "stable", "evidence_count": 8},
    "transfer": {"score": 0.21, "confidence": 0.50, "trend": "improving", "evidence_count": 5},
}

JAVA_MISCONCEPTIONS = [
    {
        "misconception_id": "MIS-001",
        "kc_id": "POLYMORPHISM",
        "type": "conceptual_confusion",
        "description": "混淆静态类型与动态类型：认为父类引用指向子类对象时会调用父类方法",
        "severity": 0.78,
        "confidence": 0.82,
        "occurrence_count": 4,
        "status": "active",
    },
    {
        "misconception_id": "MIS-002",
        "kc_id": "INHERITANCE",
        "type": "knowledge_gap",
        "description": "不理解子类构造器隐式调用 super() 的机制",
        "severity": 0.60,
        "confidence": 0.70,
        "occurrence_count": 3,
        "status": "active",
    },
]

JAVA_BEHAVIOR = {
    "activity_count_30d": 18,
    "streak_days": 4,
    "average_session_minutes": 42.0,
    "recent_topics": ["多态", "继承", "异常"],
    "frequent_revisited_topics": ["多态", "继承"],
}

JAVA_PROGRESS = 0.31

JAVA_GLOBAL_RAW = {
    "profile": {
        "user_id": DEFAULT_USER_ID,
        "display_name": "演示学生",
        "education_level": "高职三年级",
        "language": "zh",
        "background": "有基本 Python 基础，正在学习 Java OOP 面向岗位实训",
    },
    "goals": [
        {
            "goal_id": DEFAULT_GOAL_ID,
            "course_id": DEFAULT_COURSE_ID,
            "goal_name": "成绩管理实训",
            "target": "独立完成一个面向岗位的成绩管理 Java 项目",
            "priority": 1,
            "status": "active",
            "progress": 0.31,
            "target_kcs": ["CLASS", "ENCAPSULATION", "INHERITANCE", "POLYMORPHISM", "COLLECTION", "EXCEPTION", "IO"],
        }
    ],
    "preferences": {
        "preferred_mode": "example_driven",
        "learning_style_distribution": {"example_driven": 0.82, "visual": 0.30, "reading": 0.35},
        "mode_effectiveness": {
            "worked_example": {"score": 0.82, "confidence": 0.76, "sample_size": 14},
            "visual": {"score": 0.55, "confidence": 0.60, "sample_size": 8},
            "reading": {"score": 0.50, "confidence": 0.55, "sample_size": 9},
        },
        "pace_factor": 0.9,
        "scaffold_preference": 0.7,
    },
    "semantic_memory": [
        {"content": "用户通过『小矩阵示例』成功理解了 Attention 机制", "tags": ["transformer", "attention"]},
        {"content": "用户熟悉 FastAPI 与 Python 基础", "tags": ["python", "fastapi"]},
    ],
}


def _java_course_raw() -> dict:
    return {
        "schema_version": 1,
        "user_id": DEFAULT_USER_ID,
        "course_id": DEFAULT_COURSE_ID,
        "goal_id": DEFAULT_GOAL_ID,
        "progress": JAVA_PROGRESS,
        "knowledge": JAVA_KNOWLEDGE,
        "abilities": JAVA_ABILITIES,
        "misconceptions": JAVA_MISCONCEPTIONS,
        "behavior": JAVA_BEHAVIOR,
        "state_version": 37,
        "updated_at": "2026-08-10T12:00:00Z",
    }


class MockLearnerStateProvider(LearnerStateProvider):
    """固定演示数据 Provider。"""

    def __init__(self, user_id: str = DEFAULT_USER_ID, course_id: str = DEFAULT_COURSE_ID):
        self._user_id = user_id
        self._course_id = course_id

    def get_global_state(self, user_id: str) -> GlobalLearnerState:
        return parse_global_state(JAVA_GLOBAL_RAW)

    def get_course_state(self, user_id: str, course_id: str) -> CourseLearnerState:
        raw = _java_course_raw()
        raw["user_id"] = user_id
        raw["course_id"] = course_id
        return make_mock_course_state(raw, user_id=user_id, course_id=course_id)

    def get_goal(self, user_id: str, goal_id: str) -> Goal | None:
        goal_id = goal_id or DEFAULT_GOAL_ID
        for goal in parse_global_state(JAVA_GLOBAL_RAW).goals:
            if goal.goal_id == goal_id:
                return goal
        return None
