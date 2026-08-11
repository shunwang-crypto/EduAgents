"""Learner Model Repository 抽象接口。

业务代码（service/updaters）只依赖本接口，禁止直接执行 SQL。
事务语义：写方法不主动提交；由 `transaction()` 上下文统一 COMMIT/ROLLBACK。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Dict, List, Optional


class LearnerRepository(ABC):
    """Learner Model 持久化抽象。所有行数据以 dict 返回。"""

    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]: ...

    # ---- learners ---------------------------------------------------------
    @abstractmethod
    def ensure_learner(self, user_id: str, display_name: str = "") -> None: ...

    @abstractmethod
    def get_learner(self, user_id: str) -> Optional[dict]: ...

    # ---- user courses（User Course = 用户拥有；与共享 Domain 严格分离）----
    @abstractmethod
    def upsert_user_course(self, course: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_user_course(self, user_id: str, course_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_user_courses(self, user_id: str) -> List[dict]: ...

    @abstractmethod
    def delete_user_course(self, user_id: str, course_id: str) -> None: ...

    @abstractmethod
    def delete_user_course_data(self, user_id: str, course_id: str) -> None: ...

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

    # ---- kc states --------------------------------------------------------
    @abstractmethod
    def upsert_kc(self, kc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_kc(self, user_id: str, course_id: str, kc_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_kcs(self, user_id: str, course_id: str) -> List[dict]: ...

    # ---- preferences ------------------------------------------------------
    @abstractmethod
    def upsert_preference(self, pref: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_preference(self, user_id: str, preference_key: str, course_id: str = "") -> Optional[dict]: ...

    @abstractmethod
    def list_preferences(self, user_id: str, course_id: str = "") -> List[dict]: ...

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
    def delete_memory(self, user_id: str, memory_id: str) -> None: ...

    # ---- events（append-only + 幂等）--------------------------------------
    @abstractmethod
    def insert_event(self, event: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def event_exists(self, event_id: str) -> bool: ...

    @abstractmethod
    def list_events(self, user_id: str, course_id: str = "", limit: int = 200) -> List[dict]: ...

    @abstractmethod
    def count_events(self, user_id: str, course_id: str = "") -> int: ...

    # ---- change log -------------------------------------------------------
    @abstractmethod
    def insert_change(self, change: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_changes(self, user_id: str, course_id: str = "", limit: int = 100) -> List[dict]: ...

    # ---- chat -------------------------------------------------------------
    @abstractmethod
    def upsert_conversation(self, conv: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_conversation(self, conversation_id: str) -> Optional[dict]: ...

    @abstractmethod
    def get_conversation_for_user(self, user_id: str, conversation_id: str) -> Optional[dict]: ...

    @abstractmethod
    def get_course_conversation(self, user_id: str, course_id: str) -> Optional[dict]: ...

    @abstractmethod
    def insert_message(self, msg: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_messages(self, conversation_id: str, limit: int = 100) -> List[dict]: ...

    # ---- study plans ------------------------------------------------------
    @abstractmethod
    def upsert_plan(self, plan: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_plan(self, user_id: str, course_id: str) -> Optional[dict]: ...

    @abstractmethod
    def upsert_plan_step(self, step: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_plan_steps(self, plan_id: str) -> List[dict]: ...

    @abstractmethod
    def get_plan_step(self, plan_id: str, step_id: str) -> Optional[dict]: ...

    @abstractmethod
    def update_plan_progress(self, plan_id: str, progress: float) -> None: ...

    @abstractmethod
    def delete_plan(self, plan_id: str) -> None: ...

    @abstractmethod
    def get_plan_step_by_id(self, user_id: str, course_id: str, step_id: str) -> Optional[dict]: ...
