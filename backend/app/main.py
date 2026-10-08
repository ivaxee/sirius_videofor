"""Точка входа FastAPI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import close_pool, init_schema
from .routers import admin, public
from .security import RateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("SKIP_SCHEMA_INIT") != "1":
        init_schema()
    yield
    close_pool()


app = FastAPI(
    title="Пока жду — API",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(settings.requests_per_minute))
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
app.include_router(public.router)
app.include_router(admin.router)
