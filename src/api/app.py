"""
FastAPI application — REST interface for the Streamlit dashboard and external tooling.

Design: thin router layer that delegates business logic to the runner / baseline manager.
HTTP Bearer token authentication is optional (set API_KEY env var to enable).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..storage.database import init_db
from .routers import baselines, runs, test_cases

_API_KEY = os.getenv("API_KEY", "")
_bearer = HTTPBearer(auto_error=False)


def _verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    if not _API_KEY:
        return  # auth disabled when no API_KEY configured
    if credentials is None or credentials.credentials != _API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token",
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    await init_db(settings.database_url)
    yield


app = FastAPI(
    title="Prompt Regression Suite API",
    version="1.0.0",
    description="REST interface for the prompt regression test suite",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    test_cases.router,
    prefix="/test-cases",
    tags=["Test Cases"],
    dependencies=[Depends(_verify_token)],
)
app.include_router(
    runs.router,
    prefix="/runs",
    tags=["Runs"],
    dependencies=[Depends(_verify_token)],
)
app.include_router(
    baselines.router,
    prefix="/baselines",
    tags=["Baselines"],
    dependencies=[Depends(_verify_token)],
)


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}
