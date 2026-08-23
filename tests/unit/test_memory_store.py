"""Unit tests for the long-term memory store."""

import pytest

from incident_commander.services.memory_store import (
    IncidentMemoryEntry,
    recall_past_incidents,
    record_incident_resolution,
    reset_store,
)


@pytest.fixture(autouse=True)
def clean_store() -> None:
    """Reset the store before every test."""
    reset_store()


class TestMemoryStore:
    def test_record_and_recall(self) -> None:
        record_incident_resolution(
            IncidentMemoryEntry(
                incident_id="INC-MEM-001",
                service="checkout-api",
                diagnosis="Connection pool exhausted after deploy.",
                action_taken="rollback_to_previous_version",
                resolved=True,
                resolution_minutes=8,
            )
        )
        past = recall_past_incidents("checkout-api")
        assert len(past) == 1
        assert past[0]["service"] == "checkout-api"
        assert past[0]["resolved"] is True

    def test_no_records_returns_empty(self) -> None:
        past = recall_past_incidents("unknown-service")
        assert past == []

    def test_limit_respected(self) -> None:
        for i in range(5):
            record_incident_resolution(
                IncidentMemoryEntry(
                    incident_id=f"INC-MEM-{i:03d}",
                    service="api",
                    diagnosis="Issue.",
                    action_taken="rollback",
                    resolved=True,
                    resolution_minutes=5,
                )
            )
        past = recall_past_incidents("api", limit=2)
        assert len(past) <= 2

    def test_different_services_isolated(self) -> None:
        record_incident_resolution(
            IncidentMemoryEntry(
                incident_id="INC-A",
                service="service-a",
                diagnosis="Issue A.",
                action_taken="rollback",
                resolved=True,
                resolution_minutes=3,
            )
        )
        record_incident_resolution(
            IncidentMemoryEntry(
                incident_id="INC-B",
                service="service-b",
                diagnosis="Issue B.",
                action_taken="restart",
                resolved=False,
                resolution_minutes=0,
            )
        )
        past_a = recall_past_incidents("service-a")
        assert all(p["service"] == "service-a" for p in past_a)

    def test_reset_clears_all_records(self) -> None:
        record_incident_resolution(
            IncidentMemoryEntry(
                incident_id="INC-RESET",
                service="api",
                diagnosis="x",
                action_taken="y",
                resolved=True,
                resolution_minutes=1,
            )
        )
        reset_store()
        assert recall_past_incidents("api") == []
