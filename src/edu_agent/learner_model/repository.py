"""Learner Model Repository 抽象接口。

业务代码（service/updaters）只依赖本接口，禁止直接执行 SQL。
未来迁移 PostgreSQL 时只替换 sqlite_repository.py 的实现。
事务语义：写方法不主动提交；由 `transaction()` 上下文统一 COMMIT/ROLLBACK。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Dict, List, Optional


class LearnerRepository(ABC):
    """Learner Model 持久化抽象。所有行数据以 dict 返回。"""

    # ---- 事务 --------------------------------------------------------------
    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]: ...

    # ---- learners ---------------------------------------------------------
    @abstractmethod
    def ensure_learner(self, user_id: str, display_name: str = "") -> None: ...

    @abstractmethod
    def get_learner(self, user_id: str) -> Optional[dict]: ...

    @abstractmethod
    def bump_global_version(self, user_id: str) -> int: ...

    # ---- profile facts ----------------------------------------------------
    @abstractmethod
    def upsert_profile_fact(self, fact: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_profile_fact(self, user_id: str, fact_key: str) -> Optional[dict]: ...

    @abstractmethod
    def list_profile_facts(self, user_id: str) -> List[dict]: ...

    @abstractmethod
    def delete_profile_fact(self, user_id: str, fact_id: str) -> None: ...

    # ---- goals（user_id + goal_id 联合身份）-------------------------------
    @abstractmethod
    def upsert_goal(self, goal: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_goal(self, user_id: str, goal_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_goals(self, user_id: str, status: Optional[str] = None) -> List[dict]: ...

    # ---- course states ----------------------------------------------------
    @abstractmethod
    def upsert_course_state(self, state: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_course_state(self, user_id: str, course_id: str) -> Optional[dict]: ...

    @abstractmethod
    def bump_state_version(self, user_id: str, course_id: str) -> int: ...

    # ---- kc states --------------------------------------------------------
    @abstractmethod
    def upsert_kc(self, kc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_kc(self, user_id: str, course_id: str, kc_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_kcs(self, user_id: str, course_id: str) -> List[dict]: ...

    # ---- abilities --------------------------------------------------------
    @abstractmethod
    def upsert_ability(self, ability: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_ability(self, user_id: str, course_id: str, ability_type: str) -> Optional[dict]: ...

    @abstractmethod
    def list_abilities(self, user_id: str, course_id: str) -> List[dict]: ...

    # ---- preferences ------------------------------------------------------
    @abstractmethod
    def upsert_preference(self, pref: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_preference(self, user_id: str, preference_key: str, course_id: str = "") -> Optional[dict]: ...

    @abstractmethod
    def list_preferences(self, user_id: str, course_id: str = "") -> List[dict]: ...

    # ---- misconceptions（多实例：user+course+kc+key）-----------------------
    @abstractmethod
    def upsert_misconception(self, m: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_misconception(self, misconception_id: str) -> Optional[dict]: ...

    @abstractmethod
    def find_misconception(self, user_id: str, course_id: str, kc_id: str, misconception_key: str = "") -> Optional[dict]: ...

    @abstractmethod
    def list_misconceptions(self, user_id: str, course_id: str) -> List[dict]: ...

    # ---- semantic memories（课程隔离）-------------------------------------
    @abstractmethod
    def upsert_memory(self, memory: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_global_memories(self, user_id: str) -> List[dict]: ...

    @abstractmethod
    def list_course_memories(self, user_id: str, course_id: str) -> List[dict]: ...

    @abstractmethod
    def list_effective_memories(self, user_id: str, course_id: str) -> List[dict]: ...

    @abstractmethod
    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]: ...

    @abstractmethod
    def delete_memory(self, user_id: str, memory_id: str) -> None: ...

    # ---- events（append-only + 幂等）--------------------------------------
    @abstractmethod
    def insert_event(self, event: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def event_exists(self, event_id: str) -> bool: ...

    @abstractmethod
    def list_events(self, user_id: str, course_id: str = "", limit: int = 200) -> List[dict]: ...

    @abstractmethod
    def list_events_since(self, user_id: str, course_id: str, since_iso: str, limit: int = 1000) -> List[dict]: ...

    @abstractmethod
    def count_events(self, user_id: str, course_id: str = "") -> int: ...

    # ---- evidences（provenance + 幂等）------------------------------------
    @abstractmethod
    def insert_evidence(self, evidence: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def evidence_exists(self, event_id: str, entity_type: str, entity_key: str, classifier_version: str = "rule-v1") -> bool: ...

    @abstractmethod
    def list_evidences(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]: ...

    # ---- change log -------------------------------------------------------
    @abstractmethod
    def insert_change(self, change: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]: ...

    # ---- snapshots --------------------------------------------------------
    @abstractmethod
    def insert_snapshot(self, snapshot: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_snapshots(self, user_id: str, course_id: str = "", limit: int = 20) -> List[dict]: ...

    # ---- adaptive decisions ----------------------------------------------
    @abstractmethod
    def insert_decision(self, decision: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_decisions(self, user_id: str, course_id: str = "", limit: int = 50) -> List[dict]: ...

    # ---- domain courses ---------------------------------------------------
    @abstractmethod
    def upsert_domain_course(self, course: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_domain_course(self, course_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_domain_courses(self) -> List[dict]: ...

    @abstractmethod
    def upsert_domain_kc(self, kc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_domain_kcs(self, course_id: str) -> List[dict]: ...

    @abstractmethod
    def upsert_domain_relation(self, rel: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_domain_relations(self, course_id: str) -> List[dict]: ...
