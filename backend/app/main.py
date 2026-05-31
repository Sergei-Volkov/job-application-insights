from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .init_db import init_db
from .routers.analytics import router as analytics_router
from .routers.applications import router as applications_router
from .routers.discovery import router as discovery_router
from .routers.system import router as system_router
from .routers.workspace import router as workspace_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="Job Application Insights API",
    version="0.3.0",
    lifespan=lifespan,
    summary="Track job applications, ingest discovered roles, and visualize the application pipeline.",
    description=(
        "A DB-first API for a personal job search workflow. Use it to ingest jobs from a discovery "
        "worker, update application state from the UI, and analyze status, skill gaps, and trends."
    ),
    openapi_tags=[
        {"name": "system", "description": "Health and operational endpoints."},
        {"name": "applications", "description": "CRUD-style endpoints for tracked job applications."},
        {"name": "imports", "description": "Import or upsert jobs from external discovery flows."},
        {"name": "analytics", "description": "Aggregated views used by the dashboard."},
        {"name": "workspace", "description": "Generate and edit application documents in the workspace."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(system_router)
app.include_router(analytics_router)
app.include_router(applications_router)
app.include_router(workspace_router)
app.include_router(discovery_router)




