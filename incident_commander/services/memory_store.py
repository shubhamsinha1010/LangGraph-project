"""Long-term cross-thread memory using LangGraph's Store API.

The checkpointer stores per-thread (per-incident) state.
The Store stores cross-thread knowledge — patterns seen across many incidents.

What we store per service:
  - Past diagnoses and what fixed them
  - Recurring error patterns
  - Typical time-to-resolve

This lets the planner say: "checkout-api had a similar connection pool issue
3 days ago — rollback resolved it in 8 minutes" instead of starting blind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langgraph.store.memory import InMemoryStore

from incident_commander.core.logging import get_logger

logger = get_logger(__name__)

# LangGraph namespace tuple for incident memory
_NAMESPACE = ("incident_memory",)


@dataclass
class IncidentMemoryEntry:
    incident_id: str
    service: str
    diagnosis: str
    action_taken: str
    resolved: bool
    resolution_minutes: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


def get_store() -> InMemoryStore:
    """Return the singleton in-memory store.

    Swap for AsyncPostgresStore in production — the interface is identical.
    """
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store


_store: InMemoryStore | None = None


def record_incident_resolution(entry: IncidentMemoryEntry) -> None:
    """Persist a resolved incident to the store for future reference."""
    store = get_store()
    store.put(
        _NAMESPACE,
        key=entry.incident_id,
        value={
            "service": entry.service,
            "diagnosis": entry.diagnosis,
            "action_taken": entry.action_taken,
            "resolved": entry.resolved,
            "resolution_minutes": entry.resolution_minutes,
            "timestamp": entry.timestamp,
        },
    )
    logger.info(
        "memory_store.recorded",
        incident_id=entry.incident_id,
        service=entry.service,
    )


def recall_past_incidents(service: str, limit: int = 3) -> list[dict[str, Any]]:
    """Retrieve past incidents for a service to inform the current investigation."""
    store = get_store()
    results = store.search(_NAMESPACE, query=service, limit=limit * 3)
    past = [
        r.value for r in results
        if r.value.get("service") == service
    ]
    return past[:limit]


def reset_store() -> None:
    """Reset the store — used in tests."""
    global _store
    _store = InMemoryStore()
