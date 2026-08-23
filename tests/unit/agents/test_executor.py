"""Unit tests for the executor node — async, structured output mocks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.exceptions import ApprovalRequiredError
from incident_commander.core.output_models import ExecutorOutput
from incident_commander.core.state import initial_state


def _executor_llm_mock(output: ExecutorOutput) -> MagicMock:
    m = MagicMock()
    bound = MagicMock()
    m.bind_tools.return_value = bound
    bound.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=None, content="done"))
    m.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    return m


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
    async def test_raises_without_approval(self) -> None:
        from incident_commander.agents.executor import executor_node

        state = initial_state(
            incident_id="INC-002", title="T", description="D",
            severity=IncidentSeverity.HIGH, affected_service="svc",
        )
        with pytest.raises(ApprovalRequiredError):
            await executor_node(state)

    @patch("incident_commander.agents.executor.get_llm")
    async def test_executes_approved_rollback(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        from incident_commander.agents.executor import executor_node

        mock_get_llm.return_value = _executor_llm_mock(
            ExecutorOutput(
                action_taken="Rolled back checkout-api",
                tool_called="rollback_to_previous_version",
                success=True,
                result_summary="Rollback succeeded.",
                next_step="resolve",
            )
        )

        result = await executor_node(approved_state)
        assert result["execution_result"]["success"] is True
        assert result["status"] == IncidentStatus.RESOLVED

    @patch("incident_commander.agents.executor.get_llm")
    async def test_failed_execution_stays_investigating(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        from incident_commander.agents.executor import executor_node

        mock_get_llm.return_value = _executor_llm_mock(
            ExecutorOutput(
                action_taken="Attempted rollback",
                tool_called="rollback_to_previous_version",
                success=False,
                result_summary="Rollback failed.",
                next_step="escalate",
            )
        )

        result = await executor_node(approved_state)
        assert result["execution_result"]["success"] is False
        assert result["status"] == IncidentStatus.INVESTIGATING

    @patch("incident_commander.agents.executor.get_llm")
    async def test_records_to_long_term_memory(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        from incident_commander.agents.executor import executor_node
        from incident_commander.services.memory_store import recall_past_incidents, reset_store

        reset_store()
        mock_get_llm.return_value = _executor_llm_mock(
            ExecutorOutput(
                action_taken="Rolled back checkout-api",
                tool_called="rollback_to_previous_version",
                success=True,
                result_summary="Success.",
                next_step="resolve",
            )
        )

        await executor_node(approved_state)

        past = recall_past_incidents("checkout-api", limit=5)
        assert len(past) >= 1
        assert past[0]["service"] == "checkout-api"
        assert past[0]["resolved"] is True

    @patch("incident_commander.agents.executor.get_llm")
    async def test_audit_trail_records_execution(
        self, mock_get_llm: MagicMock, approved_state: dict
    ) -> None:
        from incident_commander.agents.executor import executor_node

        mock_get_llm.return_value = _executor_llm_mock(
            ExecutorOutput(
                action_taken="Rollback",
                tool_called="rollback_to_previous_version",
                success=True,
                result_summary="Done.",
                next_step="resolve",
            )
        )

        result = await executor_node(approved_state)
        trail = result["audit_trail"]
        assert len(trail) == 1
        assert trail[0]["agent"] == "executor"
        assert trail[0]["recorded_to_memory"] is True
