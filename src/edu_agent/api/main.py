"""FastAPI 应用入口。

启动：
    uvicorn edu_agent.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edu_agent.api.router import router

app = FastAPI(title="EduAgents API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发期全开；上线由宿主网关限制
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
