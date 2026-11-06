from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .bootstrap import bootstrap_defaults
from .config import get_settings
from .db import engine, init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.auto_create_db:
        await init_db()
        await bootstrap_defaults()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="AI 可编排的 FDE 应用交付中台，提供版本化应用协议、模板、评测、发布和运行时 API。",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Chromium Local Network Access may serialize a loopback Origin
        # without its development-server port. Accept loopback variations
        # only outside production; production still uses the explicit list.
        allow_origin_regex=(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$" if settings.env != "production" else None),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        # Chromium's Local Network Access preflight applies when the local
        # Vite app calls the local API. Keep this non-production so a
        # production deployment must opt into its network policy explicitly.
        allow_private_network=settings.env != "production",
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

