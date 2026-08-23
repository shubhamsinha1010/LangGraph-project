"""Integration tests for graph routing — async, mocked LLMs, no API key needed."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.output_models import (
    ChangeAnalystOutput,
    ExecutorOutput,
    LogAnalystOutput,
    MetricsAnalystOutput,
    PlannerOutput,
    ProposedAction,
    RunbookRetrieverOutput,
)
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import build_graph
from incident_commander.services.checkpointer import get_sync_checkpointer


# --------------------------------------------------------------------------- #
#  Shared fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture()
def checkpointer():
    return get_sync_checkpointer()


@pytest.fixture()
def incident_state() -> dict:
    return initial_state(
        incident_id="INC-INT-001",
        title="payments-svc: connection pool exhausted",
        description="payments-svc is returning 503s. Error rate is 22%.",
        severity=IncidentSeverity.CRITICAL,
        affected_service="payments-svc",
        alert_source="pagerduty",
    )


def _analyst_mock(output_cls, findings: list[str]) -> MagicMock:
    """Build a mock LLM that returns a structured analyst output."""
    instance = output_cls(findings=findings)
    m = MagicMock()
    bound = MagicMock()
    m.bind_tools.return_value = bound
    # run_tool_loop calls ainvoke, with_structured_output().ainvoke returns Pydantic
    bound.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=None, content="done"))
    m.with_structured_output.return_value.ainvoke = AsyncMock(return_value=instance)
    return m


def _planner_mock(destructive: bool = True) -> MagicMock:
    actions = [
        ProposedAction(
            action_type="rollback",
            description="Rollback payments-svc",
            service="payments-svc",
            is_destructive=destructive,
            priority=1,
        )
    ]
    output = PlannerOutput(
        diagnosis="Recent deploy caused connection pool exhaustion.",
        confidence=0.88,
        proposed_actions=actions,
        needs_more_investigation=False,
    )
    m = MagicMock()
    m.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    return m


def _executor_mock(success: bool = True) -> MagicMock:
    output = ExecutorOutput(
        action_taken="Rolled back payments-svc",
        tool_called="rollback_to_previous_version",
        success=success,
        result_summary="Rollback succeeded." if success else "Rollback failed.",
        next_step="resolve" if success else "escalate",
    )
    m = MagicMock()
    bound = MagicMock()
    m.bind_tools.return_value = bound
    bound.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=None, content="done"))
    m.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    return m


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #

class TestGraphRouting:
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    async def test_destructive_plan_pauses_for_hitl(
        self,
        mock_planner_fn: MagicMock,
        mock_runbook_fn: MagicMock,
        mock_change_fn: MagicMock,
        mock_metrics_fn: MagicMock,
        mock_logs_fn: MagicMock,
        incident_state: dict,
        checkpointer: Any,
    ) -> None:
        mock_logs_fn.return_value = _analyst_mock(LogAnalystOutput, ["error rate 22%"])
        mock_metrics_fn.return_value = _analyst_mock(MetricsAnalystOutput, ["p99 3000ms"])
        mock_change_fn.return_value = _analyst_mock(ChangeAnalystOutput, ["deploy 15m ago"])
        mock_runbook_fn.return_value = _analyst_mock(RunbookRetrieverOutput, ["rollback recommended"])
        mock_planner_fn.return_value = _planner_mock(destructive=True)

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-INT-001"}}
        result = await g.ainvoke(incident_state, config=config)

        assert result["status"] == IncidentStatus.AWAITING_APPROVAL
        assert len(result["proposed_actions"]) > 0
        assert result["proposed_actions"][0]["is_destructive"] is True

    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    @patch("incident_commander.agents.executor.get_llm")
    async def test_hitl_resume_after_approval(
        self,
        mock_executor_fn: MagicMock,
        mock_planner_fn: MagicMock,
        mock_runbook_fn: MagicMock,
        mock_change_fn: MagicMock,
        mock_metrics_fn: MagicMock,
        mock_logs_fn: MagicMock,
        incident_state: dict,
        checkpointer: Any,
    ) -> None:
        mock_logs_fn.return_value = _analyst_mock(LogAnalystOutput, ["error rate 22%"])
        mock_metrics_fn.return_value = _analyst_mock(MetricsAnalystOutput, ["p99 3000ms"])
        mock_change_fn.return_value = _analyst_mock(ChangeAnalystOutput, ["deploy 15m ago"])
        mock_runbook_fn.return_value = _analyst_mock(RunbookRetrieverOutput, ["rollback"])
        mock_planner_fn.return_value = _planner_mock(destructive=True)
        mock_executor_fn.return_value = _executor_mock(success=True)

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-HITL-RESUME"}}

        state = {**incident_state, "incident_id": "INC-HITL-RESUME"}
        await g.ainvoke(state, config=config)

        snapshot = g.get_state(config)
        proposed = snapshot.values.get("proposed_actions", [])
        assert len(proposed) > 0

        g.update_state(
            config,
            {
                "approved_action": proposed[0],
                "approval_notes": "Approved.",
                "status": IncidentStatus.REMEDIATING,
            },
        )

        final = await g.ainvoke(None, config=config)
        assert final["status"] == IncidentStatus.RESOLVED
        assert final["execution_result"]["success"] is True

    @patch("incident_commander.agents.executor.get_llm")
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    async def test_audit_trail_accumulates(
        self,
        mock_planner_fn: MagicMock,
        mock_runbook_fn: MagicMock,
        mock_change_fn: MagicMock,
        mock_metrics_fn: MagicMock,
        mock_logs_fn: MagicMock,
        mock_executor_fn: MagicMock,
        checkpointer: Any,
    ) -> None:
        mock_logs_fn.return_value = _analyst_mock(LogAnalystOutput, ["finding"])
        mock_metrics_fn.return_value = _analyst_mock(MetricsAnalystOutput, ["finding"])
        mock_change_fn.return_value = _analyst_mock(ChangeAnalystOutput, ["finding"])
        mock_runbook_fn.return_value = _analyst_mock(RunbookRetrieverOutput, ["finding"])
        mock_planner_fn.return_value = _planner_mock(destructive=False)
        mock_executor_fn.return_value = _executor_mock(success=True)

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-AUDIT-V2"}}
        state = initial_state(
            incident_id="INC-AUDIT-V2", title="Audit test",
            description="Testing audit", severity=IncidentSeverity.LOW,
            affected_service="api",
        )
        result = await g.ainvoke(state, config=config)

        assert len(result["audit_trail"]) >= 3
        agents = {e["agent"] for e in result["audit_trail"]}
        assert "supervisor" in agents
        assert "planner" in agents

    @patch("incident_commander.agents.executor.get_llm")
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    async def test_all_four_analysts_contribute_findings(
        self,
        mock_planner_fn: MagicMock,
        mock_runbook_fn: MagicMock,
        mock_change_fn: MagicMock,
        mock_metrics_fn: MagicMock,
        mock_logs_fn: MagicMock,
        mock_executor_fn: MagicMock,
        checkpointer: Any,
    ) -> None:
        mock_logs_fn.return_value = _analyst_mock(LogAnalystOutput, ["log finding"])
        mock_metrics_fn.return_value = _analyst_mock(MetricsAnalystOutput, ["metrics finding"])
        mock_change_fn.return_value = _analyst_mock(ChangeAnalystOutput, ["change finding"])
        mock_runbook_fn.return_value = _analyst_mock(RunbookRetrieverOutput, ["runbook finding"])
        mock_planner_fn.return_value = _planner_mock(destructive=False)
        mock_executor_fn.return_value = _executor_mock(success=True)

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-PARALLEL-V2"}}
        state = initial_state(
            incident_id="INC-PARALLEL-V2", title="Parallel test",
            description="Testing parallel", severity=IncidentSeverity.HIGH,
            affected_service="checkout-api",
        )
        result = await g.ainvoke(state, config=config)

        assert result["log_findings"] == ["log finding"]
        assert result["metrics_findings"] == ["metrics finding"]
        assert result["change_findings"] == ["change finding"]
        assert result["runbook_findings"] == ["runbook finding"]

    @patch("incident_commander.agents.executor.get_llm")
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    async def test_failed_execution_escalates(
        self,
        mock_planner_fn: MagicMock,
        mock_runbook_fn: MagicMock,
        mock_change_fn: MagicMock,
        mock_metrics_fn: MagicMock,
        mock_logs_fn: MagicMock,
        mock_executor_fn: MagicMock,
        checkpointer: Any,
    ) -> None:
        mock_logs_fn.return_value = _analyst_mock(LogAnalystOutput, ["finding"])
        mock_metrics_fn.return_value = _analyst_mock(MetricsAnalystOutput, ["finding"])
        mock_change_fn.return_value = _analyst_mock(ChangeAnalystOutput, ["finding"])
        mock_runbook_fn.return_value = _analyst_mock(RunbookRetrieverOutput, ["finding"])
        mock_planner_fn.return_value = _planner_mock(destructive=False)
        mock_executor_fn.return_value = _executor_mock(success=False)

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-FAIL-ESCALATE"}}
        state = initial_state(
            incident_id="INC-FAIL-ESCALATE", title="Failure test",
            description="Testing failure escalation", severity=IncidentSeverity.HIGH,
            affected_service="api",
        )
        result = await g.ainvoke(state, config=config)
        assert result["execution_result"]["success"] is False
