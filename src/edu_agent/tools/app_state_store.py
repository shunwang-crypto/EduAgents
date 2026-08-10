"""应用状态持久化存储（学习计划 / 学生输入 / 会话历史 / 短期 Session State）。

文件位置：
- ``data/study_plan.json``   学习计划结果 + 学生输入
- ``data/kb_sessions.json``   知识库问答多会话历史
- ``data/cache_adaptive-session-*.json``  短期会话状态（Session Store）

注：长期画像数据在 ``data/learner_model.db``（SQLite），不在此 JSON 存储。

读写都做容错：文件缺失或损坏时回退为默认值。
为保证调用方零负担，序列化策略支持三种常见类型：
- ``pydantic.BaseModel`` → ``model_dump()``
- ``dataclass`` → ``dataclasses.asdict()``
- 其它 → 直接 ``json.dumps(..., default=str)``
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"

_FILES = {
    "study_plan": DATA_DIR / "study_plan.json",
    "kb_sessions": DATA_DIR / "kb_sessions.json",
}

# 动态 key 前缀 → 允许按需落盘（如 LearnerState 缓存、Event Outbox）
_DYNAMIC_PREFIXES = ("cache_", "learning_event_", "adaptive_decision_")


def _resolve_path(key: str) -> Path | None:
    if key in _FILES:
        return _FILES[key]
    if key.startswith(_DYNAMIC_PREFIXES):
        return DATA_DIR / f"{key}.json"
    return None


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _serialize(value: Any) -> Any:
    """把值转成 JSON 可序列化结构。"""
    if isinstance(value, BaseModel):
        return {"__pydantic__": type(value).__name__, "data": value.model_dump()}
    if is_dataclass(value) and not isinstance(value, type):
        return {"__dataclass__": type(value).__name__, "data": asdict(value)}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


_RESTORE_REGISTRY: dict | None = None


def _restore_classes() -> dict:
    """惰性加载所有需要反序列化重建的模型类（按类名索引）。"""
    global _RESTORE_REGISTRY
    if _RESTORE_REGISTRY is None:
        from edu_agent.workflows.study_plan.schemas import (
            AnalysisResult,
            DecompositionResult,
            DraftPlan,
            EvaluatedResearchResult,
            KnowledgeMap,
            KnowledgeNode,
            PlanValidationResult,
            ResearchResult,
            ReviewResult,
            StudentInput,
        )

        _RESTORE_REGISTRY = {
            cls.__name__: cls
            for cls in (
                StudentInput,
                AnalysisResult,
                DecompositionResult,
                DraftPlan,
                EvaluatedResearchResult,
                KnowledgeMap,
                KnowledgeNode,
                PlanValidationResult,
                ResearchResult,
                ReviewResult,
            )
        }
    return _RESTORE_REGISTRY


def _deserialize(value: Any) -> Any:
    """反向序列化（识别写入时的 __pydantic__ / __dataclass__ 标记）。"""
    if isinstance(value, dict):
        if ("__pydantic__" in value or "__dataclass__" in value) and "data" in value:
            class_name = value.get("__pydantic__") or value.get("__dataclass__")
            data = value["data"]
            cls = _restore_classes().get(class_name)
            if cls is not None:
                try:
                    return cls(**data)
                except Exception:  # noqa: BLE001 - 字段变化时回退到 dict
                    return data
            return data
        return {k: _deserialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deserialize(item) for item in value]
    return value


def load(key: str, default: Any = None) -> Any:
    """从磁盘加载指定 key 的状态。"""
    path = _resolve_path(key)
    if path is None or not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 容错：损坏文件按 default 处理
        return default
    if raw is None:
        return default
    return _deserialize(raw)


def save(key: str, value: Any) -> None:
    """把状态写入磁盘。"""
    path = _resolve_path(key)
    if path is None:
        raise ValueError(f"未知持久化 key：{key}")
    _ensure_dir()
    payload = _serialize(value)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear(key: str) -> None:
    """清空指定 key 的持久化状态（写入 null）。"""
    path = _resolve_path(key)
    if path is None:
        return
    _ensure_dir()
    path.write_text("null", encoding="utf-8")


def clear_all() -> None:
    """清空所有持久化状态（知识库 + 学习计划 + 会话 + 画像）。"""
    from edu_agent.tools.kb_store import clear as kb_clear

    kb_clear()
    for key in _FILES:
        _ensure_dir()
        _FILES[key].write_text("null", encoding="utf-8")
