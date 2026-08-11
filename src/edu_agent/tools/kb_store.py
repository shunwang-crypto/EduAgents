"""知识库持久化存储（JSON 文件）。

把知识库块落盘到 ``data/knowledge_base.json``，使导入的教材 / GitHub 仓库在
应用重启 / Backend restart 后不丢失（取代只存在内存态的实现）。

设计要点：
- 纯标准库（json / pathlib），零第三方依赖，保证原型开箱即用；
- 存储的是 ``KbChunk`` 的序列化（course_id / doc_title / heading_path / text），
  与 ``CourseKnowledgeBase`` 的检索接口解耦；按 course_id 隔离加载；
- 读写都做容错：文件缺失或损坏时回退为空库，不抛异常。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from edu_agent.tools.course_kb import CourseKnowledgeBase, KbChunk

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
STORE_PATH = DATA_DIR / "knowledge_base.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_chunks(course_id: str | None = None) -> List[KbChunk]:
    """从磁盘加载知识库块；course_id 给定时只返回该课程块；文件损坏返回空列表。"""
    if not STORE_PATH.exists():
        return []
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 容错：损坏文件按空库处理
        return []
    if not isinstance(raw, list):
        return []
    chunks: List[KbChunk] = []
    for item in raw:
        try:
            chunk = KbChunk(**item)
        except Exception:  # noqa: BLE001 - 跳过单条损坏记录
            continue
        if course_id is None or chunk.course_id == course_id:
            chunks.append(chunk)
    return chunks


def save_chunks(chunks: List[KbChunk]) -> None:
    """把知识库块写回磁盘。"""
    _ensure_dir()
    data = [chunk.model_dump() for chunk in chunks]
    STORE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear() -> None:
    """清空持久化知识库（写入空列表）。"""
    _ensure_dir()
    STORE_PATH.write_text("[]", encoding="utf-8")


def add_markdown(course_id: str, name: str, text: str) -> int:
    """为指定课程追加一份 Markdown 教材并落盘，返回新增块数。"""
    kb = CourseKnowledgeBase.from_chunks(load_chunks(), course_id=course_id)
    added = kb.load_markdown(name, text)
    save_chunks(kb.chunks)
    return added


def add_github_repo(course_id: str, url: str, **kwargs) -> int:
    """为指定课程从 GitHub 仓库导入文档并落盘，返回新增块数。"""
    kb = CourseKnowledgeBase.from_chunks(load_chunks(), course_id=course_id)
    added = kb.load_github_repo(url, **kwargs)
    save_chunks(kb.chunks)
    return added
