import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from edu_agent.config.settings import get_settings
from edu_agent.workflows.study_plan.schemas import WebResource

_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_TIMEOUT = 15  # 秒：Tavily 挂起时不再无限等待


def _normalize_tavily_item(item: Dict[str, Any]) -> WebResource:
    return WebResource(
        title=str(item.get("title") or "Untitled"),
        url=str(item.get("url") or ""),
        summary=str(item.get("content") or item.get("snippet") or ""),
    )


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web with Tavily and return structured, failure-safe results.

    直接调 Tavily HTTP API（不用 langchain_tavily）：带 15s 硬超时，
    Tavily 挂起时快速失败，不会让 study_plan 的 research 步骤无限卡住。
    """

    settings = get_settings()
    if not settings.tavily_api_key:
        return {
            "enabled": False,
            "message": "未启用联网搜索：缺少 TAVILY_API_KEY。",
            "results": [],
        }

    start = time.time()
    print(f"[research]   → Tavily 查询: {query!r}", flush=True)
    try:
        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        request = urllib.request.Request(
            _TAVILY_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.tavily_api_key}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
                ),
            },
        )
        with urllib.request.urlopen(request, timeout=_TAVILY_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("results", data if isinstance(data, list) else [])
        if not isinstance(items, list):
            items = []

        print(
            f"[research]   ✓ Tavily 完成 {time.time() - start:.1f}s，{len(items)} 条",
            flush=True,
        )
        return {
            "enabled": True,
            "message": "联网搜索已启用。",
            "results": [_normalize_tavily_item(item) for item in items],
        }
    except Exception as exc:  # noqa: BLE001 - tool failure should not break workflow
        print(
            f"[research]   ✗ Tavily 失败 {time.time() - start:.1f}s: {exc}",
            flush=True,
        )
        return {
            "enabled": True,
            "message": f"联网搜索失败：{exc}",
            "results": [],
        }


def search_many(queries: List[str], max_results_per_query: int = 3) -> dict:
    """Run multiple searches and de-duplicate resources by URL."""

    all_resources: List[WebResource] = []
    messages: List[str] = []
    enabled = bool(get_settings().tavily_api_key)

    for query in queries:
        result = web_search(query, max_results=max_results_per_query)
        enabled = bool(result["enabled"])
        messages.append(f"{query}: {result['message']}")
        all_resources.extend(result["results"])
        if not result["enabled"]:
            break

    seen_urls = set()
    deduped: List[WebResource] = []
    for resource in all_resources:
        if resource.url and resource.url in seen_urls:
            continue
        if resource.url:
            seen_urls.add(resource.url)
        deduped.append(resource)

    return {
        "enabled": enabled,
        "message": "\n".join(messages) if messages else "未执行搜索。",
        "results": deduped,
    }
