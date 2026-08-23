"""Service locator for backend adapters.

This is the single place where concrete implementations are wired.
Swap out FakeXxxBackend for a real one here — no changes needed elsewhere.
"""

from dataclasses import dataclass

from incident_commander.tools.base import (
    ChangeBackend,
    LogBackend,
    MetricsBackend,
    RollbackBackend,
    RunbookBackend,
)
from incident_commander.tools.fake_adapters import (
    FakeChangeBackend,
    FakeLogBackend,
    FakeMetricsBackend,
    FakeRollbackBackend,
    FakeRunbookBackend,
)


@dataclass
class Backends:
    logs: LogBackend
    metrics: MetricsBackend
    changes: ChangeBackend
    runbooks: RunbookBackend
    rollback: RollbackBackend


_backends: Backends | None = None


def get_backends() -> Backends:
    """Return the singleton Backends instance, initialising with fake adapters if needed."""
    global _backends
    if _backends is None:
        _backends = Backends(
            logs=FakeLogBackend(),
            metrics=FakeMetricsBackend(),
            changes=FakeChangeBackend(),
            runbooks=FakeRunbookBackend(),
            rollback=FakeRollbackBackend(),
        )
    return _backends


def override_backends(backends: Backends) -> None:
    """Replace backends — use in tests or when plugging in real adapters."""
    global _backends
    _backends = backends
