"""Fake (in-memory) adapters for all backends.

These ship with the project so anyone can run a full incident simulation
without external credentials.  They use deterministic, realistic-looking
data seeded on the service name so demos are consistent and repeatable.

To use real backends: implement the ABC in base.py and swap via the
service locator in incident_commander/services/backends.py.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from incident_commander.tools.base import (
    ChangeBackend,
    ChangeQueryResult,
    ChangeRecord,
    LogBackend,
    LogQueryResult,
    MetricsBackend,
    MetricsQueryResult,
    RollbackBackend,
    RollbackResult,
    RunbookBackend,
    RunbookMatch,
    RunbookQueryResult,
)

# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _seed(service: str) -> int:
    """Deterministic seed from service name so results are reproducible."""
    return int(hashlib.md5(service.encode()).hexdigest()[:8], 16)  # noqa: S324


def _ts(minutes_ago: int) -> str:
    return (
        datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago)
    ).isoformat()


# --------------------------------------------------------------------------- #
#  Fake log backend
# --------------------------------------------------------------------------- #

class FakeLogBackend(LogBackend):
    """Returns realistic-looking log data for any service name."""

    _ERROR_TEMPLATES = [
        "Connection pool exhausted after {n} retries",
        "Timeout calling downstream service payments-svc (>5000ms)",
        "NullPointerException in OrderController.checkout() line 142",
        "Database deadlock detected on orders table",
        "Circuit breaker OPEN for upstream inventory-api",
    ]

    def query_errors(self, service: str, window_minutes: int = 15) -> LogQueryResult:
        seed = _seed(service)
        error_count = 200 + (seed % 300)
        error_rate = round(10 + (seed % 25), 1)
        top_errors = [
            tmpl.format(n=seed % 5 + 1)
            for tmpl in self._ERROR_TEMPLATES[: 3 + seed % 2]
        ]
        return LogQueryResult(
            service=service,
            error_count=error_count,
            error_rate_pct=error_rate,
            top_errors=top_errors,
            sample_traces=[
                f"trace-id: {hashlib.sha1(f'{service}{i}'.encode()).hexdigest()[:12]}"  # noqa: S324
                for i in range(3)
            ],
            time_window_minutes=window_minutes,
            raw_summary=(
                f"{service}: {error_count} errors in last {window_minutes}m "
                f"({error_rate}% error rate). "
                f"Top error: '{top_errors[0]}'."
            ),
        )


# --------------------------------------------------------------------------- #
#  Fake metrics backend
# --------------------------------------------------------------------------- #

class FakeMetricsBackend(MetricsBackend):

    def query_service(
        self, service: str, window_minutes: int = 15
    ) -> MetricsQueryResult:
        seed = _seed(service)
        p99 = round(1200 + (seed % 4000), 0)
        error_rate = round(8 + (seed % 30), 1)
        cpu = round(60 + (seed % 35), 1)
        mem = round(55 + (seed % 40), 1)
        anomalies = []
        if p99 > 2000:
            anomalies.append(f"p99 latency {p99}ms is 3x above 7-day baseline")
        if error_rate > 15:
            anomalies.append(f"Error rate {error_rate}% exceeds SLO threshold (1%)")
        if cpu > 80:
            anomalies.append(f"CPU {cpu}% — likely resource contention")
        return MetricsQueryResult(
            service=service,
            p99_latency_ms=p99,
            error_rate_pct=error_rate,
            request_rate_rps=round(150 + (seed % 200), 0),
            cpu_utilization_pct=cpu,
            memory_utilization_pct=mem,
            anomalies=anomalies,
            baseline_comparison={
                "p99_latency_baseline_ms": round(p99 / 3, 0),
                "error_rate_baseline_pct": 0.5,
                "deviation_multiplier": round(p99 / (p99 / 3), 1),
            },
        )


# --------------------------------------------------------------------------- #
#  Fake change backend
# --------------------------------------------------------------------------- #

class FakeChangeBackend(ChangeBackend):

    _CHANGE_TYPES = ["deploy", "config", "feature_flag", "scale"]
    _AUTHORS = ["alice@corp.com", "bob@corp.com", "ci-bot@corp.com"]

    def query_recent(
        self, service: str, lookback_hours: int = 24
    ) -> ChangeQueryResult:
        seed = _seed(service)
        num_changes = 1 + seed % 3
        changes = []
        for i in range(num_changes):
            minutes_ago = 10 + i * 40 + seed % 30
            change_type = self._CHANGE_TYPES[(seed + i) % len(self._CHANGE_TYPES)]
            changes.append(
                ChangeRecord(
                    change_id=f"deploy-{hashlib.sha1(f'{service}{i}'.encode()).hexdigest()[:8]}",  # noqa: S324
                    service=service,
                    change_type=change_type,
                    author=self._AUTHORS[(seed + i) % len(self._AUTHORS)],
                    timestamp=_ts(minutes_ago),
                    description=(
                        f"v{1 + seed % 9}.{i}.{seed % 20} — "
                        f"{'added connection pool config' if change_type == 'config' else 'new feature release'}"
                    ),
                    diff_summary=(
                        f"+42 -18 lines in {service}/src/main.py"
                        if change_type == "deploy"
                        else f"POOL_SIZE changed from 5 to {2 + seed % 4}"
                    ),
                    risk_level="high" if i == 0 else "medium",
                )
            )
        return ChangeQueryResult(
            service=service,
            recent_changes=changes,
            last_deploy_minutes_ago=10 + seed % 30,
        )


# --------------------------------------------------------------------------- #
#  Fake runbook backend
# --------------------------------------------------------------------------- #

class FakeRunbookBackend(RunbookBackend):

    _RUNBOOKS = [
        RunbookMatch(
            runbook_id="rb-001",
            title="Connection Pool Exhaustion",
            relevance_score=0.92,
            steps=[
                "Check POOL_SIZE env var — raise to 20 if below 10.",
                "Restart the affected pod to flush idle connections.",
                "If problem persists, check for long-running transactions.",
                "Scale the service horizontally if restart does not resolve.",
            ],
            typical_resolution_minutes=12,
        ),
        RunbookMatch(
            runbook_id="rb-002",
            title="High Latency / Downstream Timeout",
            relevance_score=0.78,
            steps=[
                "Identify the slow downstream dependency via trace.",
                "Check circuit breaker state — if OPEN, wait for reset.",
                "Rollback the most recent deploy if latency spiked post-deploy.",
                "Alert the owning team of the slow dependency.",
            ],
            typical_resolution_minutes=20,
        ),
        RunbookMatch(
            runbook_id="rb-003",
            title="Post-Deploy Error Spike",
            relevance_score=0.85,
            steps=[
                "Correlate error spike start time with recent deploy timestamps.",
                "Review diff for risky changes (DB queries, external calls).",
                "Rollback the deploy if error rate > 5%.",
                "Run smoke tests after rollback to confirm recovery.",
            ],
            typical_resolution_minutes=8,
        ),
    ]

    def search(self, alert_description: str, top_k: int = 3) -> RunbookQueryResult:
        seed = _seed(alert_description[:20])
        sorted_books = sorted(
            self._RUNBOOKS, key=lambda r: r.relevance_score, reverse=True
        )
        return RunbookQueryResult(
            matches=sorted_books[:top_k],
            alert_pattern=alert_description[:100],
        )


# --------------------------------------------------------------------------- #
#  Fake rollback backend
# --------------------------------------------------------------------------- #

class FakeRollbackBackend(RollbackBackend):
    """Simulates rollback.  Tracks 'current version' in memory per service."""

    def __init__(self) -> None:
        self._versions: dict[str, list[str]] = {}

    def _get_versions(self, service: str) -> list[str]:
        if service not in self._versions:
            seed = _seed(service)
            self._versions[service] = [
                f"v{1 + seed % 9}.{i}.{seed % 20}" for i in range(5, 0, -1)
            ]
        return self._versions[service]

    def rollback_to_previous(self, service: str, task_id: str) -> RollbackResult:
        versions = self._get_versions(service)
        if len(versions) < 2:
            return RollbackResult(
                service=service,
                rolled_back_to="",
                success=False,
                message="No previous version available.",
            )
        current = versions[0]
        previous = versions[1]
        # Simulate the rollback
        self._versions[service] = [previous] + versions[2:]
        return RollbackResult(
            service=service,
            rolled_back_to=previous,
            success=True,
            message=(
                f"Rolled back {service} from {current} → {previous}. "
                f"Health check passed after rollback (simulated)."
            ),
            verification={
                "health_check": "passing",
                "error_rate_after_pct": 0.3,
                "p99_latency_after_ms": 180,
            },
        )

    def rollback_to_version(
        self, service: str, version: str, task_id: str
    ) -> RollbackResult:
        versions = self._get_versions(service)
        current = versions[0]
        self._versions[service] = [version] + [v for v in versions if v != version]
        return RollbackResult(
            service=service,
            rolled_back_to=version,
            success=True,
            message=(
                f"Rolled back {service} from {current} → {version} (targeted). "
                f"Health check passed after rollback (simulated)."
            ),
            verification={
                "health_check": "passing",
                "error_rate_after_pct": 0.2,
                "p99_latency_after_ms": 160,
            },
        )
