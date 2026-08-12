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
import sqlite3
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


def load_ready_course_chunks(
    user_id: str, course_id: str, learner: Optional[LearnerModelService] = None
) -> List[Any]:
    """RAG 唯一入口（ready-source gate）：JSON chunk 存在 ≠ 可以进入 RAG。

    只有 course_sources 行存在 + 属于当前 user/course + status == ready 的 source，
    其 chunks 才被返回；failed / importing / 无 metadata 的 orphan chunk 一律不可见。
    正式路径（Chat / Plan / Lesson）都必须经此 helper，不要各自复制过滤逻辑。
    """
    learner = learner or LearnerModelService()
    ready_ids = {
        s["source_id"]
        for s in learner.repo.list_course_sources(user_id, course_id)
        if s.get("status") == "ready"
    }
    if not ready_ids:
        return []
    return [
        chunk for chunk in kb_store.load_chunks(user_id, course_id)
        if chunk.source_id in ready_ids
    ]


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
    #    import_token = 本次 import attempt 的 generation 身份：同 source 多代请求
    #    （并发 import/retry）用它区分新旧，旧请求 success/failure 都不得覆盖新代。
    existing = learner.repo.get_course_source_by_url(user_id, course_id, raw_url)
    source_id = existing["source_id"] if existing else f"SRC-{uuid.uuid4().hex[:12]}"
    display_title = _derive_title(raw_url, source_type, title)
    my_token = uuid.uuid4().hex

    now = _now_iso()
    repo = learner.repo
    try:
        repo.upsert_course_source(
            {
                "source_id": source_id,
                "user_id": user_id,
                "course_id": course_id,
                "source_type": source_type,
                "source_url": raw_url,
                "title": display_title,
                "status": "importing",
                "import_token": my_token,
                "chunk_count": existing.get("chunk_count", 0) if existing else 0,
                "error_message": "",
                "created_at": existing.get("created_at", now) if existing else now,
                "updated_at": now,
            }
        )
    except sqlite3.IntegrityError as exc:
        # FK race：course 在 validate 后被并发删除（FK CASCADE 防线）→ 404 语义
        raise KeyError(f"course not found: {course_id}") from exc

    # 4) 事务外：外部导入（可能很慢 / 可能失败）
    try:
        if source_type == "github":
            chunks = _import_github(user_id, course_id, source_id, raw_url, display_title)
        else:
            chunks = _import_web(user_id, course_id, source_id, raw_url, display_title)
    except Exception as exc:  # noqa: BLE001 - 导入失败：标记 failed，不泄露内部细节
        logger.warning("[source] import failed: user=%s course=%s url=%s", user_id, course_id, raw_url)
        # generation guard：仅当 metadata.import_token 仍是本 request 的 token 才标记 failed
        # （否则是旧请求失败，不能覆盖更新一代的成功导入）
        _discard_or_fail(repo, user_id, course_id, source_id, my_token, exc)
        cur = repo.get_course_source(user_id, course_id, source_id)
        if cur is None:
            # source 已被用户删除（或 FK CASCADE）→ 返回明确的 discarded result，绝不 return None
            return {"source_id": source_id, "status": "discarded", "source_deleted": True}
        return cur

    # 5) 重验证：导入期间课程/资料未被删除 + generation guard（旧代请求不得覆盖新代）
    if repo.get_user_course(user_id, course_id) is None:
        logger.warning("[source] course deleted during import; discard: %s", source_id)
        _safe_delete_chunks(user_id, course_id, source_id)
        return {"source_id": source_id, "status": "discarded", "course_deleted": True}
    cur = repo.get_course_source(user_id, course_id, source_id)
    if cur is None or cur.get("import_token") != my_token:
        # source 已删 / 已被更新一代 import 接管 → 旧代请求 discard，不改 status / 不删 chunks
        logger.warning("[source] stale import discarded: source=%s token=%s", source_id, my_token)
        return {"source_id": source_id, "status": "discarded",
                "source_deleted": cur is None, "stale": True}

    # 6) 落库 chunks（replace 语义，杜绝重复）+ 标记 ready
    try:
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
                "import_token": my_token,
                "chunk_count": len(chunks),
                "error_message": "",
                "created_at": existing.get("created_at", now) if existing else now,
                "updated_at": _now_iso(),
            }
        )
    except sqlite3.IntegrityError as exc:
        # FK race：finalize 时 course 已被并发删除（CASCADE 防线）→ 清理本 request chunks + 404 语义
        logger.warning("[source] course deleted before finalize; discard chunks: %s", source_id)
        _safe_delete_chunks(user_id, course_id, source_id)
        raise KeyError(f"course not found: {course_id}") from exc
    return repo.get_course_source(user_id, course_id, source_id)


def _safe_delete_chunks(user_id: str, course_id: str, source_id: str) -> None:
    """尽力删除物理 chunks（失败只记日志，ready gate 是最终防线）。"""
    try:
        kb_store.delete_source_chunks(user_id, course_id, source_id)
    except Exception:  # noqa: BLE001
        logger.warning("[source] chunk cleanup failed: %s", source_id, exc_info=True)


def _discard_or_fail(repo, user_id: str, course_id: str, source_id: str,
                     my_token: str, exc: Exception) -> None:
    """导入失败收尾：仅当仍是本 request 的代（import_token 匹配）才标 failed + 清 chunks。"""
    try:
        cur = repo.get_course_source(user_id, course_id, source_id)
    except Exception:  # noqa: BLE001
        return
    if cur is None or cur.get("import_token") != my_token:
        return  # 旧代失败 / source 已删：不覆盖新代，不删新 chunks
    _safe_delete_chunks(user_id, course_id, source_id)
    _mark_failed(repo, user_id, course_id, source_id, _readable_error(exc))


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
            "chunk_count": 0,  # 正式不变量：status=failed → chunk_count=0 → RAG inactive
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
    query = (query or "").strip()
    if not query:
        raise ValueError("搜索关键词不能为空")
    return search_internet(query, limit=limit)
