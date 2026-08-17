"""KST-lite：可达前沿 + 课程注册表 + Java OOP 示例课程。

- KST-lite：不实现完整 Knowledge Space Theory，只做
  KC DAG + prerequisite + learner mastery + reachable frontier。
- 课程注册表：Domain Model 所有用户共享，不放用户画像。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_relation import KCRelation
from edu_agent.domain.learning.knowledge_component import KnowledgeComponent


# ---------------------------------------------------------------------------
# DAG 校验
# ---------------------------------------------------------------------------


def is_dag(course: Course) -> bool:
    """检测课程 KC 关系是否构成有向无环图（仅检查 prerequisite 关系）。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {c.kc_id: WHITE for c in course.components}
    # 邻接表：from_kc -> [to_kc]（prerequisite 方向 from=前置 → to=后继）
    adj: Dict[str, List[str]] = {c.kc_id: [] for c in course.components}

    def _edge(a: str, b: str) -> None:
        if a in adj and b in adj:
            adj[a].append(b)

    for r in course.relations:
        if r.relation == "prerequisite":
            _edge(r.from_kc, r.to_kc)

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color.get(v) == GRAY:
                return False
            if color.get(v) == WHITE and not dfs(v):
                return False
        color[u] = BLACK
        return True

    return all(dfs(u) for u in color if color[u] == WHITE)


# ---------------------------------------------------------------------------
# KST-lite：可达前沿
# ---------------------------------------------------------------------------


def reachable_frontier(
    course: Course,
    mastery: Dict[str, Optional[float]],
    threshold: float = 0.7,
) -> List[str]:
    """KST-lite：返回「所有前置已满足、自身未达标」的 KC。

    UNKNOWN（mastery=None 或缺省）处理：
    - 前置 UNKNOWN → 不自动通过（不能假设已掌握），因此该 KC 不进入 frontier；
      （也不判为「确认不会」，由 recommended_next 的 PREREQUISITE_UNKNOWN 语义体现）
    - 自身 UNKNOWN → 视为未达标（可进入 frontier 学习）。
    """
    result: List[str] = []
    for kc in course.components:
        kc_id = kc.kc_id
        own = mastery.get(kc_id)
        if own is not None and own >= threshold:
            continue
        prereqs = course.prerequisites(kc_id)
        prereqs_ok = True
        for p in prereqs:
            pv = mastery.get(p)
            if pv is None or pv < threshold:  # UNKNOWN 或未掌握 → 前置未满足
                prereqs_ok = False
                break
        if prereqs_ok:
            result.append(kc_id)
    # 按传递前置数量稳定排序（前置越少的越靠前）
    return sorted(result, key=lambda kc_id: len(course.all_prerequisites_transitive(kc_id)))


def recommended_next(
    course: Course,
    mastery: Dict[str, Optional[float]],
    goal_kcs: Optional[List[str]] = None,
    threshold: float = 0.7,
) -> List[str]:
    """推荐下一步 KC：在可达前沿中，优先目标 KC 相关节点，再按掌握度升序。

    排序策略（KNOWN 优先于 UNKNOWN，避免未知当 0）：
      known weak < unknown < 其他
    """
    frontier = reachable_frontier(course, mastery, threshold)
    if not frontier:
        return []
    if not goal_kcs:
        return frontier
    goal_set = set(goal_kcs)
    relevant: List[str] = []
    rest: List[str] = []
    for kc in frontier:
        if kc in goal_set or any(d in goal_set for d in course.dependents(kc)):
            relevant.append(kc)
        else:
            rest.append(kc)
    ordered = relevant + rest

    def _sort_key(kc_id: str) -> tuple:
        value = mastery.get(kc_id)
        # 相关优先；KNOWN（有值）在 UNKNOWN 之前；再按值升序
        return (kc_id not in relevant, value is None, value if value is not None else 1.0)

    return sorted(ordered, key=_sort_key)


# ---------------------------------------------------------------------------
# 内置课程：Java OOP（与合作伙伴 KN_JAVA_* 对齐）
# ---------------------------------------------------------------------------


def java_oop_course() -> Course:
    """Java OOP 实训课程领域结构（7 个 KC）。"""
    components = [
        KnowledgeComponent("CLASS", "类与对象", category="core",
                           description="类的定义、对象创建、构造器、成员变量与方法",
                           tags=["java", "oop", "class"], difficulty="easy"),
        KnowledgeComponent("ENCAPSULATION", "封装", category="core",
                           description="访问修饰符、getter/setter、数据隐藏",
                           tags=["java", "oop", "encapsulation"], difficulty="easy"),
        KnowledgeComponent("INHERITANCE", "继承", category="core",
                           description="extends、super、方法重写、继承层次",
                           tags=["java", "oop", "inheritance"], difficulty="medium"),
        KnowledgeComponent("POLYMORPHISM", "多态", category="core",
                           description="父类引用指向子类对象、动态绑定、接口多态",
                           tags=["java", "oop", "polymorphism"], difficulty="medium"),
        KnowledgeComponent("COLLECTION", "集合框架", category="core",
                           description="List/Set/Map、泛型、遍历与常用操作",
                           tags=["java", "collection", "generic"], difficulty="medium"),
        KnowledgeComponent("EXCEPTION", "异常处理", category="core",
                           description="try/catch/finally、异常类型、自定义异常",
                           tags=["java", "exception"], difficulty="medium"),
        KnowledgeComponent("IO", "文件与流", category="core",
                           description="字节流/字符流、文件读写、IO 设计模式",
                           tags=["java", "io", "stream"], difficulty="hard"),
    ]
    relations = [
        KCRelation("CLASS", "ENCAPSULATION", "prerequisite", 1.0),
        KCRelation("ENCAPSULATION", "INHERITANCE", "prerequisite", 1.0),
        KCRelation("INHERITANCE", "POLYMORPHISM", "prerequisite", 1.0),
        KCRelation("CLASS", "COLLECTION", "prerequisite", 0.8),
        KCRelation("CLASS", "EXCEPTION", "prerequisite", 0.7),
        KCRelation("EXCEPTION", "IO", "prerequisite", 0.8),
        KCRelation("INHERITANCE", "COLLECTION", "related", 0.5),
        KCRelation("POLYMORPHISM", "COLLECTION", "related", 0.5),
        KCRelation("POLYMORPHISM", "INHERITANCE", "transfer", 0.4),
    ]
    return Course(course_id="JAVA-OOP", title="Java 面向对象实训",
                  goal="掌握 Java 面向对象编程的核心概念与工程实践",
                  components=components, relations=relations)


def llm_rag_course() -> Course:
    """LLM 应用开发：RAG 与 Agent 课程领域结构（10 个 KC）。

    依赖关系（from=前置, to=后继）：
        llm_basics ─┬─→ token_context ─→ prompt
                    │
                    └─→ embedding ─→ vector_db

        prompt + vector_db ─→ rag
        rag + prompt ─→ tool_calling ─→ agent
        agent ─┬─→ agent_memory
               └─→ agent_planning
    """
    components = [
        KnowledgeComponent("llm_basics", "LLM 基础", category="core",
                           description="大语言模型的输入输出、自回归生成与基础能力边界",
                           tags=["llm", "basics"], difficulty="easy"),
        KnowledgeComponent("token_context", "Token 与上下文", category="core",
                           description="Token 化、上下文窗口长度与截断风险",
                           tags=["llm", "token"], difficulty="medium"),
        KnowledgeComponent("prompt", "Prompt 工程", category="core",
                           description="指令、上下文、示例与角色设定等提示词设计",
                           tags=["llm", "prompt"], difficulty="medium"),
        KnowledgeComponent("embedding", "Embedding 向量", category="core",
                           description="文本向量化、语义相似度与向量距离度量",
                           tags=["llm", "embedding"], difficulty="medium"),
        KnowledgeComponent("vector_db", "向量数据库", category="core",
                           description="向量索引、近似最近邻检索与元数据过滤",
                           tags=["rag", "vector-db"], difficulty="medium"),
        KnowledgeComponent("rag", "RAG 检索增强", category="core",
                           description="检索-增强-生成流水线及其上下文拼接",
                           tags=["rag"], difficulty="hard"),
        KnowledgeComponent("tool_calling", "工具调用", category="core",
                           description="函数声明、参数抽取与执行结果回灌",
                           tags=["agent", "tool"], difficulty="hard"),
        KnowledgeComponent("agent", "Agent 智能体", category="core",
                           description="感知-决策-行动循环与多步自主任务",
                           tags=["agent"], difficulty="hard"),
        KnowledgeComponent("agent_memory", "Agent 记忆", category="core",
                           description="短期上下文与长期记忆的读写管理",
                           tags=["agent", "memory"], difficulty="medium"),
        KnowledgeComponent("agent_planning", "Agent 规划", category="core",
                           description="任务分解、计划与反思修正",
                           tags=["agent", "planning"], difficulty="hard"),
    ]
    relations = [
        KCRelation("llm_basics", "token_context", "prerequisite", 0.8),
        KCRelation("token_context", "prompt", "prerequisite", 0.6),
        KCRelation("llm_basics", "embedding", "prerequisite", 0.7),
        KCRelation("embedding", "vector_db", "prerequisite", 0.8),
        KCRelation("prompt", "rag", "prerequisite", 0.6),
        KCRelation("vector_db", "rag", "prerequisite", 0.8),
        KCRelation("rag", "tool_calling", "prerequisite", 0.4),
        KCRelation("prompt", "tool_calling", "prerequisite", 0.5),
        KCRelation("tool_calling", "agent", "prerequisite", 0.7),
        KCRelation("agent", "agent_memory", "prerequisite", 0.5),
        KCRelation("agent", "agent_planning", "prerequisite", 0.5),
    ]
    return Course(course_id="LLM-RAG", title="LLM 应用开发：RAG 与 Agent",
                  goal="独立开发基于大语言模型的 RAG 检索增强与 Agent 智能体应用",
                  components=components, relations=relations)


_COURSE_REGISTRY: Dict[str, Course] = {
    "JAVA-OOP": java_oop_course(),
    "LLM-RAG": llm_rag_course(),
}


def get_course(course_id: str) -> Optional[Course]:
    return _COURSE_REGISTRY.get(course_id)


def register_course(course: Course) -> None:
    _COURSE_REGISTRY[course.course_id] = course
