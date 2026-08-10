"""Learner Model Repository 抽象接口。

业务代码（service/updaters）只依赖本接口，禁止直接执行 SQL。
未来迁移 PostgreSQL 时只替换 sqlite_repository.py 的实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LearnerRepository(ABC):
    """Learner Model 持久化抽象。

    所有行数据以 dict 返回（键与表字段同名）。
    """

    # ---- learners ---------------------------------------------------------
    @abstractmethod
    def ensure_learner(self, user_id: str, display_name: str = "") -> None: ...

    @abstractmethod
    def get_learner(self, user_id: str) -> Optional[dict]: ...

    # ---- profile facts ----------------------------------------------------
    @abstractmethod
    def upsert_profile_fact(self, fact: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_profile_fact(self, user_id: str, fact_key: str) -> Optional[dict]: ...

    @abstractmethod
    def list_profile_facts(self, user_id: str) -> List[dict]: ...

    @abstractmethod
    def delete_profile_fact(self, user_id: str, fact_id: str) -> None: ...

    # ---- goals ------------------------------------------------------------
    @abstractmethod
    def upsert_goal(self, goal: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_goal(self, goal_id: str) -> Optional[dict]: ...

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

    # ---- misconceptions ---------------------------------------------------
    @abstractmethod
    def upsert_misconception(self, m: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_misconception(self, misconception_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_misconceptions(self, user_id: str, course_id: str) -> List[dict]: ...

    # ---- semantic memories ------------------------------------------------
    @abstractmethod
    def upsert_memory(self, memory: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_memories(self, user_id: str, course_id: str = "") -> List[dict]: ...

    @abstractmethod
    def delete_memory(self, user_id: str, memory_id: str) -> None: ...

    # ---- events (append-only) ---------------------------------------------
    @abstractmethod
    def insert_event(self, event: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_events(
        self, user_id: str, course_id: str = "", limit: int = 50
    ) -> List[dict]: ...

    @abstractmethod
    def count_events(self, user_id: str, course_id: str = "") -> int: ...

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
