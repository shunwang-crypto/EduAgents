"""策略组件包：mastery / confidence / prerequisite / misconception / preference / temporal / ability。

每个组件独立、可测试；`policy.make_decision` 负责组装。
"""

from edu_agent.adaptive.policies.ability import ability_policy  # noqa: F401
from edu_agent.adaptive.policies.confidence import confidence_policy  # noqa: F401
from edu_agent.adaptive.policies.mastery import mastery_policy  # noqa: F401
from edu_agent.adaptive.policies.misconception import misconception_policy  # noqa: F401
from edu_agent.adaptive.policies.preference import preference_policy  # noqa: F401
from edu_agent.adaptive.policies.prerequisite import prerequisite_policy  # noqa: F401
from edu_agent.adaptive.policies.temporal import temporal_policy  # noqa: F401
