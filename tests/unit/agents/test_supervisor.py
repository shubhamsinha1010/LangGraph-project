"""Unit tests for the supervisor node and conditional routing functions.

These test routing logic without invoking any LLM — pure Python, runs instantly.
"""

import pytest

from incident_commander.agents.supervisor import (
    route_after_executor,
    route_after_planner,
    route_after_supervisor,
    supervisor_node,
)
from incident_commander.core.constants import (
    IncidentSeverity,
    IncidentStatus,
    RoutingDecision,
)
from incident_commander.core.state import initial_state


class TestSupervisorNode:
    def test_initial_entry_routes_to_investigate(self) -> None:
        state = initial_state(
            incident_id="INC-001",
            title="Test",
            description="Test desc",
            severity=IncidentSeverity.HIGH,
            affected_service="svc",
        )
        result = supervisor_node(state)
        assert result["routing_decision"] == RoutingDecision.INVESTIGATE
        assert result["status"] == IncidentStatus.INVESTIGATING
        assert result["investigation_cycles"] == 1

    def test_open_status_always_investigates(self) -> None:
        state = {
            "incident_id": "INC-002",
            "status": IncidentStatus.OPEN,
            "routing_decision": None,
            "investigation_cycles": 0,
        }
        result = supervisor_node(state)
        assert result["routing_decision"] == RoutingDecision.INVESTIGATE

    def test_max_cycles_triggers_escalation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from incident_commander.core import config as cfg
        mock_settings = cfg.get_settings()
        monkeypatch.setattr(mock_settings, "max_investigation_cycles", 3)

        state = {
            "incident_id": "INC-003",
            "status": IncidentStatus.INVESTIGATING,
            "routing_decision": RoutingDecision.INVESTIGATE,
            "investigation_cycles": 3,
        }
        result = supervisor_node(state)
        assert result["routing_decision"] == RoutingDecision.ESCALATE

    def test_await_approval_sets_status(self) -> None:
        state = {
            "incident_id": "INC-004",
            "status": IncidentStatus.INVESTIGATING,
            "routing_decision": RoutingDecision.AWAIT_APPROVAL,
            "investigation_cycles": 1,
        }
        result = supervisor_node(state)
        assert result["status"] == IncidentStatus.AWAITING_APPROVAL

    def test_audit_trail_always_appended(self) -> None:
        state = initial_state(
            incident_id="INC-005",
            title="T",
            description="D",
            severity=IncidentSeverity.LOW,
            affected_service="svc",
        )
        result = supervisor_node(state)
        assert len(result["audit_trail"]) == 1
        assert "agent" in result["audit_trail"][0]


class TestRouteAfterSupervisor:
    def test_investigate_routing(self) -> None:
        assert route_after_supervisor({"routing_decision": RoutingDecision.INVESTIGATE}) == "investigate"

    def test_await_approval_routing(self) -> None:
        assert route_after_supervisor({"routing_decision": RoutingDecision.AWAIT_APPROVAL}) == "human_approval"

    def test_execute_routing(self) -> None:
        assert route_after_supervisor({"routing_decision": RoutingDecision.EXECUTE}) == "execute"

    def test_resolve_routing(self) -> None:
        assert route_after_supervisor({"routing_decision": RoutingDecision.RESOLVE}) == "resolve"

    def test_escalate_routing(self) -> None:
        assert route_after_supervisor({"routing_decision": RoutingDecision.ESCALATE}) == "escalate"

    def test_unknown_falls_back_to_resolve(self) -> None:
        assert route_after_supervisor({"routing_decision": None}) == "resolve"


class TestRouteAfterPlanner:
    def test_routes_to_supervisor_for_more_investigation(self) -> None:
        assert route_after_planner({"routing_decision": RoutingDecision.INVESTIGATE}) == "supervisor"

    def test_routes_to_human_approval_for_destructive(self) -> None:
        assert route_after_planner({"routing_decision": RoutingDecision.AWAIT_APPROVAL}) == "human_approval"

    def test_routes_to_executor_for_safe_action(self) -> None:
        assert route_after_planner({"routing_decision": RoutingDecision.EXECUTE}) == "executor"


class TestRouteAfterExecutor:
    def test_success_routes_to_resolve(self) -> None:
        state = {"execution_result": {"success": True}}
        assert route_after_executor(state) == "resolve"

    def test_failure_routes_to_escalate(self) -> None:
        state = {"execution_result": {"success": False}}
        assert route_after_executor(state) == "escalate"

    def test_missing_result_escalates(self) -> None:
        assert route_after_executor({}) == "escalate"
