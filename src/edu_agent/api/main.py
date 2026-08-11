"""FastAPI 应用入口。

启动：
    uvicorn edu_agent.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edu_agent.api.router import router
from edu_agent.config.settings import get_settings

app = FastAPI(title="EduAgents API", version="1.0.0")

_settings = get_settings()
_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
