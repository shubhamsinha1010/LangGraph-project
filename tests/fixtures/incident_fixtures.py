"""Shared test fixtures."""

import pytest

from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.state import initial_state
from incident_commander.services.backends import Backends, override_backends
from incident_commander.tools.fake_adapters import (
    FakeChangeBackend,
    FakeLogBackend,
    FakeMetricsBackend,
    FakeRollbackBackend,
    FakeRunbookBackend,
)


@pytest.fixture()
def fake_backends() -> Backends:
    """Inject fake backends and reset after each test."""
    backends = Backends(
        logs=FakeLogBackend(),
        metrics=FakeMetricsBackend(),
        changes=FakeChangeBackend(),
        runbooks=FakeRunbookBackend(),
        rollback=FakeRollbackBackend(),
    )
    override_backends(backends)
    yield backends
    override_backends(None)  # type: ignore[arg-type]


@pytest.fixture()
def checkout_incident_state() -> dict:
    return initial_state(
        incident_id="INC-001",
        title="checkout-api: high error rate (18%)",
        description=(
            "checkout-api p99 latency spiked to 2.4s and error rate is 18%. "
            "Payments are failing."
        ),
        severity=IncidentSeverity.CRITICAL,
        affected_service="checkout-api",
        alert_source="datadog",
    )


@pytest.fixture()
def investigating_state(checkout_incident_state: dict) -> dict:
    return {
        **checkout_incident_state,
        "status": IncidentStatus.INVESTIGATING,
        "log_findings": ["Error rate 18% — 3x above SLO", "Top error: Connection pool exhausted"],
        "metrics_findings": ["p99 latency 2400ms — 3x above baseline"],
        "change_findings": ["Deploy deploy-abc12345 by ci-bot 15 minutes ago — high risk"],
        "runbook_findings": ["Runbook: Post-Deploy Error Spike — rollback recommended"],
        "investigation_cycles": 1,
    }


@pytest.fixture()
def planned_state(investigating_state: dict) -> dict:
    return {
        **investigating_state,
        "diagnosis": "Recent deploy likely caused connection pool exhaustion.",
        "confidence": 0.85,
        "proposed_actions": [
            {
                "action_type": "rollback",
                "description": "Roll back checkout-api to previous version",
                "service": "checkout-api",
                "is_destructive": True,
                "priority": 1,
            }
        ],
        "needs_more_investigation": False,
    }


@pytest.fixture()
def approved_state(planned_state: dict) -> dict:
    return {
        **planned_state,
        "approved_action": planned_state["proposed_actions"][0],
        "approval_notes": "Approved by on-call engineer.",
        "status": IncidentStatus.REMEDIATING,
    }
