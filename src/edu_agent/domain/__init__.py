"""领域层：课程知识结构（Course / KnowledgeComponent / KCRelation / KST-lite）。

Domain Model 所有用户共享，不放用户画像。
"""

from edu_agent.domain.learning.course import Course  # noqa: F401
from edu_agent.domain.learning.kc_graph import (  # noqa: F401
    get_course,
    java_oop_course,
    reachable_frontier,
    recommended_next,
    register_course,
)
from edu_agent.domain.learning.kc_relation import KCRelation  # noqa: F401
from edu_agent.domain.learning.knowledge_component import KnowledgeComponent  # noqa: F401
