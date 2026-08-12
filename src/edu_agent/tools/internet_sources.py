"""联网资料辅助（Internet Search / Web Extract）。

- 不新增第三方依赖：复用已列入 requirements 的 ``langchain-tavily``
  （``TavilySearch`` / ``TavilyExtract``）。
- 所有外部 URL 必须经过 ``is_valid_source_url`` 校验，拒绝 file/ftp/javascript/data
  以及 localhost / 私网地址，避免任意协议流入第三方工具。
- 搜索结果只是候选，用户选择后才导入（不自动进知识库）。
- 缺 TAVILY_API_KEY 时抛出可读错误（不含 traceback / key），由上层转成 failed 状态。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

_GITHUB_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
# 拒绝私有/回环/链路本地地址（literal IP 或 localhost）。
_PRIVATE_HOST_RE = re.compile(
    r"(localhost|127\.0\.0\.1|0\.0\.0\.0|::1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+"
    r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+)$",
    re.IGNORECASE,
)

# 单 source 原始内容上限（约 1.5MB），进入 chunk 前还会再截取。
_MAX_RAW_CHARS = 1_500_000


def is_valid_source_url(url: str) -> bool:
    """仅允许 http/https；拒绝 file/ftp/javascript/data 与内网/回环地址。"""
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    if not re.match(r"^https?://", low):
        return False
    for bad in ("file:", "ftp:", "javascript:", "data:"):
        if low.startswith(bad):
            return False
    from urllib.parse import urlparse

    host = (urlparse(u).hostname or "").lower()
    if not host:
        return False
    if _PRIVATE_HOST_RE.search(host):
        return False
    return True


def detect_source_type(url: str) -> str:
    """校验 URL 并返回来源类型：github / web。

    非法 URL 抛 ``ValueError``（信息隐藏，不含内部细节）。
    """
    u = (url or "").strip()
    if not is_valid_source_url(u):
        raise ValueError("仅支持 http/https 链接（拒绝 file/ftp/javascript/data 与内网地址）")
    if _GITHUB_RE.match(u):
        return "github"
    return "web"


def _require_tavily() -> None:
    if not os.getenv("TAVILY_API_KEY"):
        raise RuntimeError("未配置 TAVILY_API_KEY，无法访问互联网资料")


def search_internet(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """用 Tavily 搜索互联网资料，normalize 为 {title, url, snippet} 列表（最多 5–8 条）。

    搜索结果仅为候选，不直接导入知识库。
    """
    _require_tavily()
    from langchain_tavily import TavilySearch

    tool = TavilySearch(
        max_results=limit,
        topic="general",
        include_answer=False,
        include_raw_content=False,
    )
    result = tool.invoke({"query": query})
    raw_results = (result or {}).get("results") or []
    out: List[Dict[str, str]] = []
    for r in raw_results[:limit]:
        snippet = (r.get("content") or "")[:300]
        out.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": (r.get("url") or "").strip(),
                "snippet": snippet.strip(),
            }
        )
    return out


def extract_web(url: str, max_chars: int = _MAX_RAW_CHARS) -> str:
    """用 TavilyExtract 抓取单个 Web URL 的 markdown 正文。

    返回原始内容（已按上限截取）；空内容抛 ``RuntimeError``（导入失败）。
    """
    _require_tavily()
    from langchain_tavily import TavilyExtract

    u = url.strip()
    if not is_valid_source_url(u):
        raise ValueError("仅支持 http/https 链接")
    tool = TavilyExtract(extract_depth="basic", include_images=False, format="markdown")
    result = tool.invoke({"urls": [u]})
    raw_results = (result or {}).get("results") or []
    if not raw_results:
        raise RuntimeError("未能抓取网页内容")
    raw = raw_results[0].get("raw_content") or ""
    if not raw.strip():
        raise RuntimeError("网页内容为空")
    return raw[:max_chars]
