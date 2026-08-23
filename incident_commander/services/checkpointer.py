"""Checkpointer + Store factory.

- Development: MemorySaver + InMemoryStore (no external deps, in-process)
- Production: AsyncPostgresSaver + AsyncPostgresStore (durable, survives restarts)

Both the checkpointer (per-thread state) and the store (cross-thread memory)
share the same Postgres connection pool in production, minimising connections.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from incident_commander.core.config import get_settings
from incident_commander.core.exceptions import CheckpointError
from incident_commander.core.logging import get_logger

logger = get_logger(__name__)


def get_sync_checkpointer() -> MemorySaver:
    """Return an in-memory checkpointer for tests and local dev."""
    return MemorySaver()


def get_sync_store() -> InMemoryStore:
    """Return an in-memory store for tests and local dev."""
    return InMemoryStore()


@asynccontextmanager
async def get_async_checkpointer() -> AsyncGenerator[object, None]:
    """Async context manager yielding a production-ready checkpointer.

    Yields MemorySaver in dev (no Postgres needed).
    Yields AsyncPostgresSaver in production (durable, ACID-compliant).
    """
    settings = get_settings()

    if settings.checkpoint_backend == "memory" or not settings.database_url:
        logger.info("checkpointer.using_memory")
        yield MemorySaver()
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import]
    except ImportError as exc:
        raise CheckpointError(
            "psycopg and langgraph-checkpoint-postgres are required for postgres backend."
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


@asynccontextmanager
async def get_async_store() -> AsyncGenerator[object, None]:
    """Async context manager yielding a production-ready Store.

    Yields InMemoryStore in dev.
    Yields AsyncPostgresStore in production so long-term incident memory
    (cross-thread) survives restarts.
    """
    settings = get_settings()

    if settings.checkpoint_backend == "memory" or not settings.database_url:
        logger.info("store.using_memory")
        yield InMemoryStore()
        return

    try:
        from langgraph.store.postgres.aio import AsyncPostgresStore  # type: ignore[import]
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import]
    except ImportError as exc:
        raise CheckpointError(
            "psycopg and langgraph-store-postgres are required for postgres store."
        ) from exc

    logger.info("store.using_postgres")
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=5,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    store = AsyncPostgresStore(pool)
    await store.setup()
    try:
        yield store
    finally:
        await pool.close()
