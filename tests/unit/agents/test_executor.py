"""Unit tests for the executor node."""

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from incident_commander.agents.executor import executor_node
from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.exceptions import ApprovalRequiredError
from incident_commander.core.state import initial_state


def _ai_msg(payload: dict) -> AIMessage:
    return AIMessage(content=json.dumps(payload))


@pytest.fixture()
def approved_state() -> dict:
    base = initial_state(
        incident_id="INC-001",
        title="checkout-api error spike",
        description="Errors",
        severity=IncidentSeverity.CRITICAL,
        affected_service="checkout-api",
    )
    return {
        **base,
        "approved_action": {
            "action_type": "rollback",
            "description": "Rollback checkout-api",
            "service": "checkout-api",
            "is_destructive": True,
        },
        "approval_notes": "Approved.",
        "status": IncidentStatus.REMEDIATING,
    }


class TestExecutorNode:
    def test_raises_without_approval(self) -> None:
        state = initial_state(
            incident_id="INC-002",
            title="T",
            description="D",
            severity=IncidentSeverity.HIGH,
            affected_service="svc",
        )
        with pytest.raises(ApprovalRequiredError):
            executor_node(state)

    @patch("incident_commander.agents.executor.get_llm")
    def test_executes_approved_rollback(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        mock_llm = MagicMock()
        bound_llm = MagicMock()
        mock_llm.bind_tools.return_value = bound_llm
        bound_llm.invoke.return_value = _ai_msg({
            "action_taken": "Rolled back checkout-api",
            "tool_called": "rollback_to_previous_version",
            "success": True,
            "result_summary": "Rollback succeeded. Health check passing.",
            "next_step": "monitor",
        })
        mock_get_llm.return_value = mock_llm

        result = executor_node(approved_state)
        assert result["execution_result"]["success"] is True
        assert result["status"] == IncidentStatus.RESOLVED

    @patch("incident_commander.agents.executor.get_llm")
    def test_failed_execution_stays_investigating(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        mock_llm = MagicMock()
        bound_llm = MagicMock()
        mock_llm.bind_tools.return_value = bound_llm
        bound_llm.invoke.return_value = _ai_msg({
            "action_taken": "Attempted rollback",
            "tool_called": "rollback_to_previous_version",
            "success": False,
            "result_summary": "Rollback failed.",
            "next_step": "escalate",
        })
        mock_get_llm.return_value = mock_llm

        result = executor_node(approved_state)
        assert result["execution_result"]["success"] is False
        assert result["status"] == IncidentStatus.INVESTIGATING

    @patch("incident_commander.agents.executor.get_llm")
    def test_audit_trail_records_execution(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        mock_llm = MagicMock()
        bound_llm = MagicMock()
        mock_llm.bind_tools.return_value = bound_llm
        bound_llm.invoke.return_value = _ai_msg({
            "action_taken": "Rollback",
            "tool_called": "rollback_to_previous_version",
            "success": True,
            "result_summary": "Done.",
            "next_step": "resolve",
        })
        mock_get_llm.return_value = mock_llm

        result = executor_node(approved_state)
        trail = result["audit_trail"]
        assert len(trail) == 1
        assert trail[0]["agent"] == "executor"
        assert "success" in trail[0]
