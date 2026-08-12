"""CourseSourceService：课程资料（Web / GitHub / Internet Search）。

只负责：list_sources / add_source / delete_source / search_sources。
业务规则（强制）：
- 所有操作第一步校验课程归属（repo.get_user_course），否则 KeyError → 404；
  绝不允许先抓 URL 后 ownership check。
- add_source 顺序：ownership → 规范化 URL → 检测类型 → 建/复用 source_id →
  status=importing → **事务外**做外部导入（GitHub clone / Tavily 抓取）→
  重验证 course/source 仍存在 → replace_source_chunks → status=ready。
- 失败：status=failed + 简短可读 error_message；绝不返回 traceback / API key / 内部路径。
- 重复 URL：复用同一 source_id（replace 语义，不会 A/A/A 叠加）。
- 删除：清 source chunks + 删除 course_sources 行；导入中删除的资料，导入完成后
  重验证 source 已不存在 → 丢弃陈旧结果。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from edu_agent.learner_model.service import LearnerModelService
from edu_agent.tools import kb_store
from edu_agent.tools.course_kb import CourseKnowledgeBase
from edu_agent.tools.github_importer import GitHubImportError, import_github_repo
from edu_agent.tools.internet_sources import (
    detect_source_type,
    extract_web,
    is_valid_source_url,
    search_internet,
)

logger = logging.getLogger(__name__)

# 单资料正文上限（进入 chunk 前再截一次，避免巨库撑爆存储）
_MAX_DOC_CHARS = 120_000
_MAX_DOCS = 50
_MAX_TOTAL_CHUNKS = 3000


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _derive_title(url: str, source_type: str, provided: str) -> str:
    provided = (provided or "").strip()
    if provided:
        return provided
    if source_type == "github":
        # https://github.com/owner/repo → owner/repo
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
    from urllib.parse import urlparse

    host = urlparse(url).hostname or url
    return host


def _build_chunks(
    user_id: str, course_id: str, source_id: str, source_type: str, url: str, title: str, text: str
) -> List[Any]:
    """把一份资料文本切成带完整归属的 KbChunk（导入在事务外完成，这里只构造）。"""
    kb = CourseKnowledgeBase(user_id=user_id, course_id=course_id)
    text = (text or "").strip()
    if not text:
        raise RuntimeError("资料内容为空")
    capped = text[:_MAX_DOC_CHARS]
    kb.load_markdown(source_id, source_type, url, title, capped)
    return kb.chunks


def list_sources(
    user_id: str, course_id: str, learner: Optional[LearnerModelService] = None
) -> List[dict]:
    """列出当前用户当前课程的全部资料（含 status / chunk_count）。"""
    learner = learner or LearnerModelService()
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    return learner.repo.list_course_sources(user_id, course_id)


def add_source(
    user_id: str,
    course_id: str,
    url: str,
    title: str = "",
    learner: Optional[LearnerModelService] = None,
) -> dict:
    """新增（或重试）一个课程资料：Web 抓取 / GitHub 导入，落库为 user+course 双隔离 chunk。"""
    learner = learner or LearnerModelService()
    # 1) ownership 优先
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    # 2) 规范化 + 校验 + 检测类型（非法 URL 直接抛可读错误）
    raw_url = (url or "").strip()
    if not is_valid_source_url(raw_url):
        raise ValueError("仅支持 http/https 链接（拒绝 file/ftp/javascript/data 与内网地址）")
    source_type = detect_source_type(raw_url)

    # 3) 建/复用 source_id（同 URL 复用，支持 failed 重试）
    existing = learner.repo.get_course_source_by_url(user_id, course_id, raw_url)
    source_id = existing["source_id"] if existing else f"SRC-{uuid.uuid4().hex[:12]}"
    display_title = _derive_title(raw_url, source_type, title)

    now = _now_iso()
    repo = learner.repo
    repo.upsert_course_source(
        {
            "source_id": source_id,
            "user_id": user_id,
            "course_id": course_id,
            "source_type": source_type,
            "source_url": raw_url,
            "title": display_title,
            "status": "importing",
            "chunk_count": existing.get("chunk_count", 0) if existing else 0,
            "error_message": "",
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
    )

    # 4) 事务外：外部导入（可能很慢 / 可能失败）
    try:
        if source_type == "github":
            chunks = _import_github(user_id, course_id, source_id, raw_url, display_title)
        else:
            chunks = _import_web(user_id, course_id, source_id, raw_url, display_title)
    except Exception as exc:  # noqa: BLE001 - 导入失败：标记 failed，不泄露内部细节
        logger.warning("[source] import failed: user=%s course=%s url=%s", user_id, course_id, raw_url)
        _mark_failed(repo, user_id, course_id, source_id, _readable_error(exc))
        return repo.get_course_source(user_id, course_id, source_id)

    # 5) 重验证：导入期间课程/资料未被删除 → 否则丢弃陈旧结果
    if repo.get_user_course(user_id, course_id) is None:
        logger.warning("[source] course deleted during import; discard: %s", source_id)
        kb_store.delete_source_chunks(user_id, course_id, source_id)
        return {"source_id": source_id, "status": "discarded", "course_deleted": True}
    if repo.get_course_source(user_id, course_id, source_id) is None:
        logger.warning("[source] source deleted during import; discard: %s", source_id)
        kb_store.delete_source_chunks(user_id, course_id, source_id)
        return {"source_id": source_id, "status": "discarded", "source_deleted": True}

    # 6) 落库 chunks（replace 语义，杜绝重复）+ 标记 ready
    kb_store.replace_source_chunks(user_id, course_id, source_id, chunks)
    repo.upsert_course_source(
        {
            "source_id": source_id,
            "user_id": user_id,
            "course_id": course_id,
            "source_type": source_type,
            "source_url": raw_url,
            "title": display_title,
            "status": "ready",
            "chunk_count": len(chunks),
            "error_message": "",
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": _now_iso(),
        }
    )
    return repo.get_course_source(user_id, course_id, source_id)


def _import_github(
    user_id: str, course_id: str, source_id: str, url: str, title: str
) -> List[Any]:
    docs = import_github_repo(url)
    kb = CourseKnowledgeBase(user_id=user_id, course_id=course_id)
    total = 0
    for name, text in list(docs.items())[:_MAX_DOCS]:
        kb.load_markdown(source_id, "github", url, name, (text or "").strip()[:_MAX_DOC_CHARS])
        total = len(kb.chunks)
        if total >= _MAX_TOTAL_CHUNKS:
            break
    if not kb.chunks:
        raise RuntimeError("仓库中未找到可导入的文档内容")
    return kb.chunks


def _import_web(
    user_id: str, course_id: str, source_id: str, url: str, title: str
) -> List[Any]:
    text = extract_web(url)
    return _build_chunks(user_id, course_id, source_id, "web", url, title, text)


def _mark_failed(repo, user_id: str, course_id: str, source_id: str, message: str) -> None:
    row = repo.get_course_source(user_id, course_id, source_id)
    if row is None:
        return
    repo.upsert_course_source(
        {
            **row,
            "status": "failed",
            "error_message": message[:200],
            "updated_at": _now_iso(),
        }
    )


def _readable_error(exc: Exception) -> str:
    """把导入异常转成简短可读信息（剥离内部路径 / key / traceback）。"""
    if isinstance(exc, GitHubImportError):
        msg = str(exc)
    elif isinstance(exc, ValueError):
        msg = str(exc)
    else:
        msg = "资料导入失败，请稍后重试"
    return msg[:200]


def delete_source(
    user_id: str, course_id: str, source_id: str, learner: Optional[LearnerModelService] = None
) -> None:
    """删除资料：先 ownership 校验，再删 chunks + course_sources 行。"""
    learner = learner or LearnerModelService()
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    if learner.repo.get_course_source(user_id, course_id, source_id) is None:
        raise KeyError(f"source not found: {source_id}")
    kb_store.delete_source_chunks(user_id, course_id, source_id)
    learner.repo.delete_course_source(user_id, course_id, source_id)


def search_sources(
    user_id: str,
    course_id: str,
    query: str,
    limit: int = 5,
    learner: Optional[LearnerModelService] = None,
) -> List[Dict[str, str]]:
    """搜索互联网资料候选（不直接导入）。课程必须存在（X-User-Id + course scoped）。"""
    learner = learner or LearnerModelService()
    if learner.repo.get_user_course(user_id, course_id) is None:
        raise KeyError(f"course not found: {course_id}")
    return search_internet(query, limit=limit)
