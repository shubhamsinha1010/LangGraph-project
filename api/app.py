"""FastAPI application factory.

Uses the factory pattern (create_app) so tests can create isolated app
instances without starting a real server.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.logging import RequestLoggingMiddleware
from api.routes import health, incidents, webhooks
from incident_commander.core.config import get_settings
from incident_commander.core.logging import configure_logging, get_logger
from incident_commander.services.tracing import configure_tracing

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing()
    logger.info(
        "app.startup",
        environment=settings.environment,
        checkpoint_backend=settings.checkpoint_backend,
        tracing=settings.langchain_tracing_v2,
    )
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Incident Commander",
        description=(
            "Production-grade SRE multi-agent copilot built on LangGraph. "
            "Investigates alerts, diagnoses root cause, and executes approved remediations."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")

    return app


app = create_app()
