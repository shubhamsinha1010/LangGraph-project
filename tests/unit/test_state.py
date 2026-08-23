"""Unit tests for state reducers and initial_state factory."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.state import IncidentStateDict, _merge_findings, initial_state


class TestInitialState:
    def test_all_required_fields_present(self) -> None:
        state = initial_state(
            incident_id="INC-001",
            title="Test incident",
            description="Something broke",
            severity=IncidentSeverity.HIGH,
            affected_service="api",
        )
        assert state["incident_id"] == "INC-001"
        assert state["status"] == IncidentStatus.OPEN
        assert state["investigation_cycles"] == 0
        assert state["needs_more_investigation"] is True

    def test_findings_start_empty(self) -> None:
        state = initial_state(
            incident_id="INC-002",
            title="Test",
            description="Desc",
            severity=IncidentSeverity.LOW,
            affected_service="svc",
        )
        assert state["log_findings"] == []
        assert state["metrics_findings"] == []
        assert state["change_findings"] == []
        assert state["runbook_findings"] == []

    def test_default_alert_source(self) -> None:
        state = initial_state(
            incident_id="INC-003",
            title="T",
            description="D",
            severity=IncidentSeverity.MEDIUM,
            affected_service="svc",
        )
        assert state["alert_source"] == "manual"


class TestMergeFindingsReducer:
    def test_appends_new_items(self) -> None:
        left = ["finding A", "finding B"]
        right = ["finding C"]
        result = _merge_findings(left, right)
        assert result == ["finding A", "finding B", "finding C"]

    def test_deduplicates_existing_items(self) -> None:
        left = ["finding A", "finding B"]
        right = ["finding B", "finding C"]
        result = _merge_findings(left, right)
        assert result == ["finding A", "finding B", "finding C"]

    def test_empty_left(self) -> None:
        result = _merge_findings([], ["finding X"])
        assert result == ["finding X"]

    def test_empty_right(self) -> None:
        result = _merge_findings(["finding X"], [])
        assert result == ["finding X"]

    def test_both_empty(self) -> None:
        result = _merge_findings([], [])
        assert result == []

    def test_order_preserved(self) -> None:
        left = ["a", "b", "c"]
        right = ["d", "e"]
        result = _merge_findings(left, right)
        assert result == ["a", "b", "c", "d", "e"]
