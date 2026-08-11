"""SQLite 并发回归：FastAPI 同步路由在线程池执行，共享 LearnerModelService
必须线程安全（thread-local 连接），不能跨线程复用连接、不能同连接并发损坏。"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def lm_db_path(tmp_path):
    path = str(tmp_path / "concurrent.db")
    os.environ["LEARNER_MODEL_DB_PATH"] = path
    yield path


def _shared_service():
    from edu_agent.learner_model.service import LearnerModelService

    return LearnerModelService()


def test_shared_service_concurrent_read_write(lm_db_path):
    """多线程并发读写共享单例：无异常、事件无丢失。"""
    from edu_agent.learner_model.service import LearnerModelService

    svc = LearnerModelService()
    svc.repo.ensure_learner("STU-001")
    svc.repo.upsert_course_state(
        {
            "user_id": "STU-001", "course_id": "PY", "current_goal_id": "",
            "progress": 0.0, "current_stage": "", "state_version": 1,
            "updated_at": "2026-08-11T00:00:00Z",
        }
    )

    def worker(i: int) -> None:
        s = LearnerModelService()  # 命中进程共享单例
        s.repo.get_course_state("STU-001", "PY")
        s.repo.get_course_conversation("STU-001", "")
        s.apply_event(
            {
                "event_type": "CHAT_MESSAGE_SENT", "user_id": "STU-001",
                "course_id": "PY", "payload": {"q": f"msg-{i}"},
            }
        )

    errors: list = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker, i) for i in range(24)]
        for f in futures:
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    assert errors == []
    assert svc.repo.count_events("STU-001", "PY") == 24


def test_concurrent_transaction_rollback_isolation(lm_db_path):
    """transaction() 事务深度是线程本地的：一个线程的回滚不影响其他线程。"""
    from edu_agent.learner_model.service import LearnerModelService

    svc = LearnerModelService()
    svc.repo.ensure_learner("STU-002")

    def bad_tx() -> None:
        with svc.repo.transaction():
            svc.repo.upsert_course_state(
                {
                    "user_id": "STU-002", "course_id": "BAD", "current_goal_id": "",
                    "progress": 0.0, "current_stage": "", "state_version": 1,
                    "updated_at": "2026-08-11T00:00:00Z",
                }
            )
            raise RuntimeError("boom")

    def good_tx() -> None:
        with svc.repo.transaction():
            svc.repo.upsert_course_state(
                {
                    "user_id": "STU-002", "course_id": "GOOD", "current_goal_id": "",
                    "progress": 0.0, "current_stage": "", "state_version": 1,
                    "updated_at": "2026-08-11T00:00:00Z",
                }
            )

    with ThreadPoolExecutor(max_workers=2) as ex:
        bad_f = ex.submit(bad_tx)
        good_f = ex.submit(good_tx)
        with pytest.raises(RuntimeError):
            bad_f.result()
        good_f.result()

    # 失败事务回滚（BAD 不存在），成功事务提交（GOOD 存在）
    assert svc.repo.get_course_state("STU-002", "BAD") is None
    assert svc.repo.get_course_state("STU-002", "GOOD") is not None
