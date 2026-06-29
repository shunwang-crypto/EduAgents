from typing import Any, Dict, List

from edu_agent.config.settings import get_settings
from edu_agent.workflows.study_plan.schemas import WebResource


def _normalize_tavily_item(item: Dict[str, Any]) -> WebResource:
    return WebResource(
        title=str(item.get("title") or "Untitled"),
        url=str(item.get("url") or ""),
        summary=str(item.get("content") or item.get("snippet") or ""),
    )


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web with Tavily and return structured, failure-safe results."""

    settings = get_settings()
    if not settings.tavily_api_key:
        return {
            "enabled": False,
            "message": "未启用联网搜索：缺少 TAVILY_API_KEY。",
            "results": [],
        }

    try:
        from langchain_tavily import TavilySearch

        tool = TavilySearch(
            max_results=max_results,
            tavily_api_key=settings.tavily_api_key,
        )
        raw_results = tool.invoke({"query": query})
        items = raw_results.get("results", raw_results)
        if not isinstance(items, list):
            items = []

        return {
            "enabled": True,
            "message": "联网搜索已启用。",
            "results": [_normalize_tavily_item(item) for item in items],
        }
    except Exception as exc:  # noqa: BLE001 - tool failure should not break workflow
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
