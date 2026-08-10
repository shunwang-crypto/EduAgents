"""MockLearnerStateProvider：合作伙伴服务未启动时的开发/测试/演示数据。

数据来自当前已知 Java 实训场景（仅包含合作伙伴已提供的字段）：
- 学生：林同学；课程：JAVA-OOP；目标：GOAL-JAVA-001；进度 .31
- knowledge mastery：CLASS .90 / EXCEPTION .50 / IO .33 / POLYMORPHISM .24 /
                     INHERITANCE .17 / ENCAPSULATION .00 / COLLECTION .00
- abilities：understanding .30 / application .31 / reasoning .32 /
             expression .30 / reflection .30 / transfer .21
- preference：example_driven；visual .30；reading .35

未知字段（confidence / trend / evidence_count / misconception / behavior 等）
必须保持 null —— 禁止人为编造。
"""

from __future__ import annotations

from edu_agent.integrations.learner_state.adapter import make_mock_course_state, parse_global_state
from edu_agent.integrations.learner_state.provider import LearnerStateProvider
from edu_agent.integrations.learner_state.schemas import CourseLearnerState, GlobalLearnerState, Goal

DEFAULT_USER_ID = "STU-001"
DEFAULT_COURSE_ID = "JAVA-OOP"
DEFAULT_GOAL_ID = "GOAL-JAVA-001"

# Java OOP 课程知识掌握度（只含合作伙伴已提供的 mastery；其余字段保持 None）
JAVA_KNOWLEDGE = [
    {"kc_id": "CLASS", "name": "类与对象", "mastery": 0.90, "status": "mastered"},
    {"kc_id": "EXCEPTION", "name": "异常处理", "mastery": 0.50, "status": "learning"},
    {"kc_id": "IO", "name": "文件与流", "mastery": 0.33, "status": "weak"},
    {"kc_id": "POLYMORPHISM", "name": "多态", "mastery": 0.24, "status": "weak"},
    {"kc_id": "INHERITANCE", "name": "继承", "mastery": 0.17, "status": "weak"},
    {"kc_id": "ENCAPSULATION", "name": "封装", "mastery": 0.00, "status": "unknown"},
    {"kc_id": "COLLECTION", "name": "集合框架", "mastery": 0.00, "status": "unknown"},
]

JAVA_ABILITIES = {
    "understanding": {"score": 0.30},
    "application": {"score": 0.31},
    "reasoning": {"score": 0.32},
    "expression": {"score": 0.30},
    "reflection": {"score": 0.30},
    "transfer": {"score": 0.21},
}

JAVA_PROGRESS = 0.31

JAVA_GLOBAL_RAW = {
    "profile": {
        "user_id": DEFAULT_USER_ID,
        "display_name": "林同学",
        "education_level": "",
        "language": "zh",
        "background": "",
    },
    "goals": [
        {
            "goal_id": DEFAULT_GOAL_ID,
            "course_id": DEFAULT_COURSE_ID,
            "goal_name": "Java OOP 实训",
            "target": "掌握 Java 面向对象核心并完成岗位实训项目",
            "priority": 1,
            "status": "active",
            "progress": 0.31,
            "target_kcs": ["CLASS", "ENCAPSULATION", "INHERITANCE", "POLYMORPHISM", "COLLECTION", "EXCEPTION", "IO"],
        }
    ],
    "preferences": {
        "preferred_mode": "example_driven",
        "learning_style_distribution": {"example_driven": 0.82, "visual": 0.30, "reading": 0.35},
        # mode_effectiveness / pace_factor / scaffold_preference 未知，保持空/默认，不编造
    },
    "semantic_memory": [],
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
        # misconceptions / behavior 未知 → 保持空，不编造
        "state_version": None,
        "updated_at": None,
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
