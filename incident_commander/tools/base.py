"""Abstract base classes for all tools.

Following the Dependency Inversion Principle: agents depend on interfaces,
not on concrete implementations (fake vs real adapter).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogQueryResult:
    service: str
    error_count: int
    error_rate_pct: float
    top_errors: list[str]
    sample_traces: list[str]
    time_window_minutes: int
    raw_summary: str


@dataclass
class MetricsQueryResult:
    service: str
    p99_latency_ms: float
    error_rate_pct: float
    request_rate_rps: float
    cpu_utilization_pct: float
    memory_utilization_pct: float
    anomalies: list[str]
    baseline_comparison: dict[str, Any]


@dataclass
class ChangeRecord:
    change_id: str
    service: str
    change_type: str  # deploy | config | feature_flag | scale
    author: str
    timestamp: str
    description: str
    diff_summary: str
    risk_level: str


@dataclass
class ChangeQueryResult:
    service: str
    recent_changes: list[ChangeRecord]
    last_deploy_minutes_ago: int | None


@dataclass
class RunbookMatch:
    runbook_id: str
    title: str
    relevance_score: float
    steps: list[str]
    typical_resolution_minutes: int


@dataclass
class RunbookQueryResult:
    matches: list[RunbookMatch]
    alert_pattern: str


@dataclass
class RollbackResult:
    service: str
    rolled_back_to: str
    success: bool
    message: str
    verification: dict[str, Any] = field(default_factory=dict)


class LogBackend(ABC):
    """Interface for querying log stores (Datadog, CloudWatch, Elastic, etc.)."""

    @abstractmethod
    def query_errors(
        self, service: str, window_minutes: int = 15
    ) -> LogQueryResult:
        ...


class MetricsBackend(ABC):
    """Interface for querying metrics stores (Datadog, Prometheus, etc.)."""

    @abstractmethod
    def query_service(
        self, service: str, window_minutes: int = 15
    ) -> MetricsQueryResult:
        ...


class ChangeBackend(ABC):
    """Interface for querying deployment / change history."""

    @abstractmethod
    def query_recent(
        self, service: str, lookback_hours: int = 24
    ) -> ChangeQueryResult:
        ...


class RunbookBackend(ABC):
    """Interface for retrieving runbooks by alert pattern."""

    @abstractmethod
    def search(self, alert_description: str, top_k: int = 3) -> RunbookQueryResult:
        ...


class RollbackBackend(ABC):
    """Interface for executing rollback actions."""

    @abstractmethod
    def rollback_to_previous(self, service: str, task_id: str) -> RollbackResult:
        ...

    @abstractmethod
    def rollback_to_version(
        self, service: str, version: str, task_id: str
    ) -> RollbackResult:
        ...
