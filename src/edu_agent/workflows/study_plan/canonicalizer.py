"""KnowledgeMap → canonical KCGraph 规范化层。

职责：
1. 将 LLM / fallback 生成的 ``KnowledgeMap``（草稿，可能含 ``knowledge-N``
   这类基于位置的临时 ID 或中英文标题）转换为 *canonical* ``Course``
   （即运行时唯一的 ``KCGraph`` 来源）。
2. 规范 KC ID：
   - 优先接受 LLM 提供的合法 ``canonical_key``；
   - 否则根据规范化标题派生稳定 ID ``kc_<sha1(normalized_title)[:10]>``
     （跨进程稳定，不依赖 Python ``hash()``）。
3. 检测并处理：重复 canonical key、悬空前置、自环、环、空图、重复边。
4. 校验生成的无环结构（DAG），对非法图给出明确 validation errors。

本模块不创建第二套 domain graph，最终产物就是 ``domain.learning.Course``。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from edu_agent.domain.learning.course import Course
from edu_agent.domain.learning.kc_relation import KCRelation
from edu_agent.domain.learning.knowledge_component import KnowledgeComponent
from edu_agent.workflows.study_plan.schemas import KnowledgeMap, KnowledgeNode

logger = logging.getLogger(__name__)

# canonical KC ID 规范：小写字母开头，仅含小写字母/数字/下划线，长度 2-63。
_CANONICAL_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

# 禁止作为合法 canonical ID 的基于位置的临时 ID（如 knowledge-1）。
_LEGACY_TEMP_RE = re.compile(r"^knowledge-\d+$", re.IGNORECASE)


@dataclass
class GraphValidationError:
    kind: str  # duplicate_node / dangling_prerequisite / self_loop / cycle / empty_graph / duplicate_edge / unknown_relation
    message: str


@dataclass
class CanonicalizationResult:
    course: Optional[Course] = None
    validation_errors: List[GraphValidationError] = field(default_factory=list)
    collisions: List[str] = field(default_factory=list)
    fallback_used: bool = False
    node_id_map: Dict[str, str] = field(default_factory=dict)  # 原始 temp_id/旧 id → canonical id
    graph_source: str = "generated"


def normalize_title(title: str) -> str:
    """规范化标题：去空白、转小写、折叠空白。用于稳定派生 ID。"""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def normalize_canonical_key(key: Optional[str]) -> Optional[str]:
    """规范化候选 canonical_key；非法返回 None。"""
    if not key:
        return None
    key = (key or "").strip().lower()
    if not _CANONICAL_RE.match(key) or _LEGACY_TEMP_RE.match(key):
        return None
    return key


def canonicalize_kc_id(title: str, canonical_key: Optional[str] = None) -> str:
    """根据标题与可选 canonical_key 生成稳定 canonical KC ID。

    - ``canonical_key`` 合法（且满足规范、不是 ``knowledge-N``）→ 直接使用；
    - 否则按规范化标题派生 ``kc_<sha1(normalized_title)[:10]>``。
    """
    ck = normalize_canonical_key(canonical_key)
    if ck:
        return ck
    norm = normalize_title(title)
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]
    return f"kc_{digest}"


def _stable_sort_key(node: dict) -> Tuple[int, str]:
    """按 (难度, 标题) 排序，作为安全 DAG 回退的拓扑依据。"""
    diff_rank = {"easy": 0, "medium": 1, "hard": 2}.get((node.get("difficulty") or "").lower(), 1)
    return (diff_rank, node.get("title") or node.get("id") or "")


class KnowledgeMapCanonicalizer:
    """将 ``KnowledgeMap`` 草稿转换为可校验的 ``Course``（canonical KCGraph）。"""

    def __init__(self, course_id: str, display_name: str, goal: str = ""):
        self.course_id = course_id
        self.display_name = display_name
        self.goal = goal

    def canonicalize(
        self,
        km: KnowledgeMap,
        reuse_graph: Optional[Course] = None,
    ) -> CanonicalizationResult:
        """主入口。

        :param km: LLM / fallback 生成的知识地图草稿。
        :param reuse_graph: 已有的 canonical 图（用于复用相同知识点的 canonical ID，
            提高重新生成时的 ID 稳定性，并保留 Learner History 关联）。
        :return: 规范化结果。
        """
        result = CanonicalizationResult(graph_source="generated")
        nodes = km.nodes or []

        if not nodes:
            result.validation_errors.append(
                GraphValidationError("empty_graph", "generated knowledge graph has no nodes")
            )
            return result

        # 兼容 KnowledgeNode / dict / 测试 FakeNode：统一为 dict 访问。
        nodes = [_node_as_dict(n) for n in (km.nodes or [])]
        if not nodes:
            result.validation_errors.append(
                GraphValidationError("empty_graph", "generated knowledge graph has no nodes")
            )
            return result

        # 1) 复用映射：规范化标题 → 旧 canonical id（提高重新生成稳定性）。
        reuse_by_title: Dict[str, str] = {}
        if reuse_graph is not None:
            for c in reuse_graph.components:
                reuse_by_title[normalize_title(c.title)] = c.kc_id

        # 2) 为每个草稿节点分配 canonical id，并检测 duplicate canonical key。
        id_map: Dict[str, str] = {}  # 原始 node.id（可能是 knowledge-N 或已 canonical）→ canonical id
        canonical_ids: Dict[str, str] = {}  # canonical id → 原始 node.id（用于检测覆盖）
        title_to_canonical: Dict[str, str] = {}

        for node in nodes:
            source_id = node.get("id")
            node_title = node.get("title", "")
            # 优先使用复用图中同标题的 canonical id。
            reused = reuse_by_title.get(normalize_title(node_title))
            if reused and reused not in canonical_ids:
                cid = reused
            else:
                cid = canonicalize_kc_id(node_title, node.get("canonical_key"))

            # duplicate canonical key 检测：若不同原始节点映射到同一 cid，
            # 后一个改用确定性 fallback（基于原始 id 派生）并记录 collision。
            if cid in canonical_ids and canonical_ids[cid] != source_id:
                orig = canonical_ids[cid]
                other_title = next(
                    (n.get("title", "") for n in nodes if n.get("id") == orig), orig
                )
                # 若规范化标题实际相同 → 视为同一知识点，合并（后者复用前者 id）。
                if normalize_title(node_title) == normalize_title(other_title):
                    id_map[source_id] = cid
                    result.collisions.append(cid)
                    continue
                # 不同知识点但 key 冲突 → 派生稳定 fallback。
                digest = hashlib.sha1(
                    f"{cid}:{source_id}".encode("utf-8")
                ).hexdigest()[:10]
                cid = f"kc_{digest}"
                logger.warning(
                    "duplicate canonical key detected; reassigned %s -> %s",
                    source_id,
                    cid,
                )
                result.collisions.append(cid)

            # 若派生出的 cid 仍与已有冲突，再加熵。
            while cid in canonical_ids and canonical_ids[cid] != source_id:
                digest = hashlib.sha1(
                    f"{cid}:{source_id}:x".encode("utf-8")
                ).hexdigest()[:10]
                cid = f"kc_{digest}"

            id_map[source_id] = cid
            canonical_ids[cid] = source_id
            title_to_canonical[normalize_title(node_title)] = cid

        # 3) 构建 KCs 与关系（prerequisites 在草稿阶段可能引用原始/临时 id）。
        components: List[KnowledgeComponent] = []
        relations: List[KCRelation] = []
        seen_edges: set = set()

        # 建立名称 → canonical id 的映射，用于把“前置知识点名称”解析为 canonical id。
        title_to_cid: Dict[str, str] = {}
        for node in nodes:
            cid = id_map[node.get("id")]
            title_to_cid[normalize_title(node.get("title", ""))] = cid

        # P1-2：同一 canonical KC 必须真正去重为一个 component。
        # （duplicate canonical key 合并后，多个原始节点可能映射到同一 cid。）
        seen_components: set = set()
        for node in nodes:
            cid = id_map[node.get("id")]
            if cid in seen_components:
                continue
            seen_components.add(cid)
            components.append(
                KnowledgeComponent(
                    kc_id=cid,
                    title=node.get("title", ""),
                    category=node.get("category") or "core",
                    description=node.get("summary") or "",
                    difficulty=(node.get("difficulty") or "medium"),
                    tags=[],
                )
            )

            for prereq in node.get("prerequisites") or []:
                prereq_norm = normalize_title(prereq)
                # 前置可能引用：原始 node.id、canonical id、或节点标题。
                pre_cid = (
                    id_map.get(prereq)
                    or title_to_cid.get(prereq_norm)
                    or (prereq if prereq in canonical_ids else None)
                )
                if pre_cid is None:
                    # 悬空前置：记录错误，但继续构造（后续 validation 拦截）。
                    result.validation_errors.append(
                        GraphValidationError(
                            "dangling_prerequisite",
                            f"node '{cid}' references unknown prerequisite '{prereq}'",
                        )
                    )
                    continue
                if pre_cid == cid:
                    result.validation_errors.append(
                        GraphValidationError(
                            "self_loop", f"node '{cid}' lists itself as prerequisite"
                        )
                    )
                    continue
                edge = (pre_cid, cid)
                if edge in seen_edges:
                    result.validation_errors.append(
                        GraphValidationError(
                            "duplicate_edge", f"duplicate prerequisite {pre_cid} -> {cid}"
                        )
                    )
                    continue
                seen_edges.add(edge)
                relations.append(
                    KCRelation(from_kc=pre_cid, to_kc=cid, relation="prerequisite")
                )

        # 4) 组装 Course 并做 DAG 校验。
        course = Course.from_dag(
            course_id=self.course_id,
            display_name=self.display_name,
            goal=self.goal,
            nodes=[(c.kc_id, c.title, c.category) for c in components],
            edges=[(r.from_kc, r.to_kc, r.relation) for r in relations],
        )
        course._components = components
        course._relations = relations

        # 空图 / 环 检测。
        if not course.components:
            result.validation_errors.append(
                GraphValidationError("empty_graph", "no valid KC components after canonicalization")
            )
        if not _is_dag(components, relations):
            result.validation_errors.append(
                GraphValidationError("cycle", "knowledge graph contains a cycle")
            )

        if result.validation_errors:
            result.course = None
            return result

        result.course = course
        result.node_id_map = id_map
        return result

    def safe_fallback(self, km: KnowledgeMap) -> Course:
        """LLM 修复仍失败时，根据 difficulty + 原始顺序构造安全 DAG。

        保留历史行为：只返回 Course。完整结果（含 temp→canonical id 映射）见
        ``safe_fallback_result``，供调用方同步 remap StudyPlan。
        """
        return self.safe_fallback_result(km).course

    def safe_fallback_result(self, km: KnowledgeMap) -> CanonicalizationResult:
        """LLM 修复仍失败时构造安全 DAG，并返回 temp id → canonical id 映射。

        P0-3 invariant：fallback 的 canonical 图与其 temp id 映射必须同时产出，
        否则 StudyPlan 会保留草稿的 ``knowledge-N`` 等临时 id，而 Graph 已是
        canonical id，导致 Plan/Graph/Tutor/LearnerModel 的 KC id 不一致。

        同时处理 P1-2：同一 canonical KC（同标题 / 同 canonical_key）必须真正
        合并为一个 component，并完成 prerequisite 重映射（含去重、去自环）。
        """
        raw_nodes = [_node_as_dict(n) for n in (km.nodes or [])]
        # 稳定排序：难度低优先、标题字典序（保证 DAG 确定性）。
        nodes = sorted(raw_nodes, key=lambda n: _stable_sort_key(n))
        result_collisions: List[str] = []

        # 1) 为每个草稿节点分配 canonical id，并检测重复 canonical KC（真正去重）。
        id_map: Dict[str, str] = {}          # 原始 node.id → canonical id
        canonical_ids: Dict[str, str] = {}   # canonical id → 原始 node.id
        title_to_cid: Dict[str, str] = {}    # 规范化标题 → canonical id
        for node in nodes:
            source_id = node.get("id")
            cid = canonicalize_kc_id(node.get("title", ""), node.get("canonical_key"))
            other_title = canonical_ids.get(cid)
            if other_title is not None and other_title != source_id:
                # 不同原始节点映射到同一 canonical id：
                # 若规范化标题相同 → 视为同一知识点，合并（复用已有 component）。
                other = next((nd for nd in nodes if nd.get("id") == other_title), None)
                if (other or {}).get("title", "") and \
                        normalize_title(node.get("title", "")) == normalize_title((other or {}).get("title", "")):
                    id_map[source_id] = cid
                    result_collisions.append(cid)
                    continue
                # 不同知识点但 canonical_key 冲突 → 派生稳定 fallback id。
                digest = hashlib.sha1(f"{cid}:{source_id}".encode("utf-8")).hexdigest()[:10]
                cid = f"kc_{digest}"
            # 仍冲突则再加熵。
            while cid in canonical_ids and canonical_ids[cid] != source_id:
                digest = hashlib.sha1(f"{cid}:{source_id}:x".encode("utf-8")).hexdigest()[:10]
                cid = f"kc_{digest}"
            id_map[source_id] = cid
            canonical_ids[cid] = source_id
            title_to_cid[normalize_title(node.get("title", ""))] = cid

        # 2) 构造 components（去重：只对每个 canonical id 保留首个原始节点）。
        components: List[KnowledgeComponent] = []
        seen_components: set = set()
        for node in nodes:
            cid = id_map[node.get("id")]
            if cid in seen_components:
                continue
            seen_components.add(cid)
            components.append(
                KnowledgeComponent(
                    kc_id=cid,
                    title=node.get("title", ""),
                    category=node.get("category") or "core",
                    description=node.get("summary") or "",
                    difficulty=(node.get("difficulty") or "medium"),
                    tags=[],
                )
            )

        # 3) 只映射原始 prerequisites：顺序和节点列表本身不是依赖证据。
        #    关键：保证 DAG——只允许“排序在前的知识点”作为“排序在后的知识点”的前置。
        #    若原始草稿带环，环上后出现的边会被丢弃；不再用顺序补边。
        order = [c.kc_id for c in components]
        pos = {cid: i for i, cid in enumerate(order)}
        relations: List[KCRelation] = []
        seen_edges: set = set()
        for node in nodes:
            cid = id_map[node.get("id")]
            for prereq in node.get("prerequisites") or []:
                prereq_norm = normalize_title(prereq)
                pre_cid = (
                    id_map.get(prereq)
                    or title_to_cid.get(prereq_norm)
                    or (prereq if prereq in canonical_ids else None)
                )
                if pre_cid is None or pre_cid == cid or pre_cid not in seen_components:
                    continue
                # DAG 保证：跳过回边（pre 在 cid 之后 → 会成环）。
                if pos.get(pre_cid, -1) >= pos.get(cid, len(order)):
                    continue
                edge = (pre_cid, cid)
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                relations.append(KCRelation(from_kc=pre_cid, to_kc=cid, relation="prerequisite"))

        logger.warning("using safe fallback DAG for course %s", self.course_id)
        course = Course.from_dag(
            course_id=self.course_id,
            display_name=self.display_name,
            goal=self.goal,
            nodes=[(c.kc_id, c.title, c.category) for c in components],
            edges=[(r.from_kc, r.to_kc, r.relation) for r in relations],
        )
        course._components = components
        course._relations = relations
        return CanonicalizationResult(
            course=course,
            fallback_used=True,
            node_id_map=id_map,
            graph_source="generated",
            collisions=result_collisions,
        )


def _node_as_dict(node) -> dict:
    """兼容 KnowledgeNode / dict / 测试 FakeNode（字段存于 _d 或 model_dump）。"""
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        try:
            return node.model_dump()
        except Exception:
            pass
    if hasattr(node, "_d") and isinstance(node._d, dict):
        return node._d
    if hasattr(node, "__dict__"):
        return dict(node.__dict__)
    return {}


def _is_dag(components: List[KnowledgeComponent], relations: List[KCRelation]) -> bool:
    from edu_agent.domain.learning.kc_graph import is_dag

    course = Course.from_dag(
        course_id="_tmp",
        display_name="_tmp",
        goal="",
        nodes=[(c.kc_id, c.title, c.category) for c in components],
        edges=[(r.from_kc, r.to_kc, r.relation) for r in relations],
    )
    course._components = components
    course._relations = relations
    return is_dag(course)
