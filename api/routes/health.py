"""Health-check endpoints — required for Kubernetes readiness/liveness probes."""

from fastapi import APIRouter
from pydantic import BaseModel

from incident_commander.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    environment: str
    checkpoint_backend: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        checkpoint_backend=settings.checkpoint_backend,
    )


@router.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    """Kubernetes readiness probe — returns 200 only when graph is importable."""
    from incident_commander.graphs.supervisor import graph  # noqa: F401  (import verifies)
    settings = get_settings()
    return HealthResponse(
        status="ready",
        environment=settings.environment,
        checkpoint_backend=settings.checkpoint_backend,
    )
