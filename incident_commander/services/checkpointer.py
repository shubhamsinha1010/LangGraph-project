"""Checkpointer factory.

- Development: MemorySaver (no external deps, in-process)
- Production: AsyncPostgresSaver (durable, survives restarts)

The graph never calls this directly — the graph factory (graphs/supervisor.py)
calls get_checkpointer() at startup so the rest of the codebase is insulated
from the backend choice.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver

from incident_commander.core.config import get_settings
from incident_commander.core.exceptions import CheckpointError
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def get_sync_checkpointer() -> MemorySaver:
    """Return an in-memory checkpointer for tests and local dev."""
    return MemorySaver()


@asynccontextmanager
async def get_async_checkpointer() -> AsyncGenerator[object, None]:
    """Async context manager that yields a production-ready checkpointer.

    Yields MemorySaver in development or when the postgres backend is not
    configured, and AsyncPostgresSaver in production.
    """
    settings = get_settings()

    if settings.checkpoint_backend == "memory" or not settings.database_url:
        logger.info("checkpointer.using_memory")
        yield MemorySaver()
        return

    # Lazy import — psycopg is only required in production
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import]
    except ImportError as exc:
        raise CheckpointError(
            "psycopg and langgraph-checkpoint-postgres are required for the "
            "postgres checkpoint backend. Run: pip install psycopg[binary,pool] "
            "langgraph-checkpoint-postgres"
        ) from exc

    logger.info("checkpointer.using_postgres", url=settings.database_url[:30] + "...")
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=10,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    try:
        yield checkpointer
    finally:
        await pool.close()
