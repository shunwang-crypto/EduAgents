"""知识库持久化存储（JSON 文件）。

把知识库块落盘到 ``data/knowledge_base.json``，使导入的教材 / GitHub 仓库在
应用重启 / Backend restart 后不丢失（取代只存在内存态的实现）。

设计要点：
- 纯标准库（json / pathlib），零第三方依赖，保证原型开箱即用；
- 存储的是 ``KbChunk`` 的序列化（user_id / course_id / source_id / source_type /
  source_url / doc_title / heading_path / text），按 user+course 双隔离加载；
- **并发安全**：模块级 RLock 把「读-改-写」包在同一个锁内，杜绝并发 lost update；
  ``load_chunks`` 同锁读，保证同进程读到一致 snapshot（RLock 允许内部 helper 嵌套）；
- **原子写**：同目录临时文件 → write → flush → fsync → os.replace，避免半写文件；
- 坏 JSON 不伪装成空库：仅「文件不存在」返回空；真实损坏（JSONDecodeError /
  PermissionError / OSError）记录日志并抛出；
- 旧版/未知字段记录在读时不参与当前 RAG，但任何增删写回都会原样保留，避免一次
  无关的课程清理把尚未迁移的数据静默清空；
- 每个 source 使用 replace 语义（replace_source_chunks），重新导入同一资料替换旧块，
  绝不 append 重复；
- 外部网络导入（GitHub clone / Tavily 抓取）由调用方在事务外完成后，把构造好的
  KbChunk 列表交给 replace_source_chunks 落盘。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import List

from edu_agent.tools.course_kb import CourseKnowledgeBase, KbChunk

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
STORE_PATH = DATA_DIR / "knowledge_base.json"

# 同进程 read-modify-write 互斥：防止并发 lost update（RLock 允许嵌套）
_STORE_LOCK = threading.RLock()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> tuple[List[KbChunk], List[object]]:
    """加载当前格式 chunks，并把无法解析的旧记录作为 opaque 数据保留。

    仅「文件不存在」视为空库；真实损坏（JSONDecodeError / PermissionError /
    OSError）记录日志并抛出，绝不伪装成「知识库为空」。单条旧格式记录因为
    无法可靠推断 user/course/source 归属，当前 RAG 不读取它，但后续写操作必须
    原样带回文件，绝不能把“无法解析”误当成“可以删除”。
    """
    if not STORE_PATH.exists():
        return [], []
    raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"knowledge base store corrupted: expected list, got {type(raw).__name__}"
        )
    chunks: List[KbChunk] = []
    preserved: List[object] = []
    for item in raw:
        try:
            chunk = KbChunk(**item)
        except Exception:  # noqa: BLE001 - 旧格式无法归属，只隔离读取，不允许丢数据
            preserved.append(item)
            continue
        chunks.append(chunk)
    if preserved:
        logger.warning(
            "[kb_store] preserving %d legacy/unsupported chunk records; "
            "they are excluded from scoped RAG until migrated",
            len(preserved),
        )
    return chunks, preserved


def _load_all() -> List[KbChunk]:
    """从磁盘加载当前格式知识库块（不做 user/course 过滤）。"""
    chunks, _ = _load_store()
    return chunks


def _save_all(chunks: List[KbChunk], preserved: List[object] | None = None) -> None:
    """原子写回：同目录临时文件 → write → flush → fsync → os.replace。

    避免并发读者看到半写文件 / 进程崩溃留下截断 JSON。
    """
    _ensure_dir()
    # preserved 是无法安全迁移的旧格式 JSON 记录。除 clear() 这种显式全清操作外，
    # 所有 read-modify-write 都必须把它们原样带回，防止静默数据丢失。
    data = json.dumps(
        [*(preserved or []), *(chunk.model_dump() for chunk in chunks)],
        ensure_ascii=False,
        indent=2,
    )
    fd, tmp_path = tempfile.mkstemp(dir=str(STORE_PATH.parent), prefix=".kb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, STORE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_chunks(user_id: str, course_id: str) -> List[KbChunk]:
    """严格按 user_id + course_id 双隔离加载知识库块（不跨用户、不跨课程）。

    与写操作共用 RLock，保证同进程读到一致 snapshot。
    """
    with _STORE_LOCK:
        return [
            chunk
            for chunk in _load_all()
            if chunk.user_id == user_id and chunk.course_id == course_id
        ]


def replace_source_chunks(
    user_id: str, course_id: str, source_id: str, chunks: List[KbChunk]
) -> None:
    """用新块替换某资料的全部块（删除旧 source 块再追加，杜绝重复 append）。

    重新导入同一 source 时调用，保证幂等：旧 chunks 被整体替换，不会 A/A/A 叠加。
    整个 read-modify-write 在同一个 RLock 内，并发调用不会丢更新。
    """
    with _STORE_LOCK:
        loaded, preserved = _load_store()
        existing = [
            chunk
            for chunk in loaded
            if not (chunk.user_id == user_id and chunk.course_id == course_id
                    and chunk.source_id == source_id)
        ]
        existing.extend(chunks)
        _save_all(existing, preserved)


def delete_source_chunks(user_id: str, course_id: str, source_id: str) -> None:
    """删除某资料的全部块。"""
    with _STORE_LOCK:
        loaded, preserved = _load_store()
        remaining = [
            chunk
            for chunk in loaded
            if not (chunk.user_id == user_id and chunk.course_id == course_id
                    and chunk.source_id == source_id)
        ]
        _save_all(remaining, preserved)


def delete_course_chunks(user_id: str, course_id: str) -> None:
    """删除某用户某课程的全部块（删除课程时调用，避免孤儿资料块残留）。"""
    with _STORE_LOCK:
        loaded, preserved = _load_store()
        remaining = [
            chunk
            for chunk in loaded
            if not (chunk.user_id == user_id and chunk.course_id == course_id)
        ]
        _save_all(remaining, preserved)


def clear() -> None:
    """清空持久化知识库（写入空列表）。"""
    with _STORE_LOCK:
        _save_all([])
