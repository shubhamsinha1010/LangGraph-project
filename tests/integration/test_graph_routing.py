"""Integration tests for graph routing — run end-to-end with mocked LLMs.

These tests validate:
- The supervisor correctly fans out to investigators.
- Planner output drives routing decisions.
- HITL interrupt fires before human_approval node.
- update_state + resume correctly continues from checkpoint.
- Audit trail accumulates across all nodes.

No real LLM API calls are made.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import build_graph
from incident_commander.services.checkpointer import get_sync_checkpointer


def _ai_msg(payload: dict) -> AIMessage:
    return AIMessage(content=json.dumps(payload))


@pytest.fixture()
def checkpointer():
    return get_sync_checkpointer()


@pytest.fixture()
def incident_state() -> dict:
    return initial_state(
        incident_id="INC-TEST-001",
        title="payments-svc: connection pool exhausted",
        description="payments-svc is returning 503s. Error rate is 22%.",
        severity=IncidentSeverity.CRITICAL,
        affected_service="payments-svc",
        alert_source="pagerduty",
    )


@pytest.fixture()
def mock_analyst_llm() -> MagicMock:
    """LLM that always returns a one-finding JSON for analyst nodes."""
    m = MagicMock()
    bound = MagicMock()
    m.bind_tools.return_value = bound
    bound.invoke.return_value = _ai_msg({
        "findings": ["Mock finding from analyst"],
        "error_rate_pct": 22.0,
        "p99_latency_ms": 3000.0,
        "anomalies": ["High error rate"],
        "most_likely_culprit_change_id": "deploy-abc123",
        "best_runbook_id": "rb-003",
        "best_runbook_title": "Post-Deploy Error Spike",
        "recommended_steps": ["Rollback the deploy"],
    })
    return m


@pytest.fixture()
def mock_planner_llm_destructive() -> MagicMock:
    """Planner that returns a destructive rollback action."""
    m = MagicMock()
    m.invoke.return_value = _ai_msg({
        "diagnosis": "Recent deploy caused connection pool exhaustion.",
        "confidence": 0.88,
        "proposed_actions": [
            {
                "action_type": "rollback",
                "description": "Roll back payments-svc to previous version",
                "service": "payments-svc",
                "is_destructive": True,
                "priority": 1,
            }
        ],
        "needs_more_investigation": False,
    })
    return m


@pytest.fixture()
def mock_planner_llm_safe() -> MagicMock:
    """Planner that returns a safe (non-destructive) action."""
    m = MagicMock()
    m.invoke.return_value = _ai_msg({
        "diagnosis": "Traffic spike, no action needed.",
        "confidence": 0.9,
        "proposed_actions": [
            {
                "action_type": "investigate_more",
                "description": "Monitor for 10 minutes",
                "service": "payments-svc",
                "is_destructive": False,
                "priority": 1,
            }
        ],
        "needs_more_investigation": False,
    })
    return m


class TestGraphRouting:
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    def test_destructive_plan_pauses_for_hitl(
        self,
        mock_planner: MagicMock,
        mock_runbook: MagicMock,
        mock_change: MagicMock,
        mock_metrics: MagicMock,
        mock_logs: MagicMock,
        mock_analyst_llm: MagicMock,
        mock_planner_llm_destructive: MagicMock,
        incident_state: dict,
        checkpointer: Any,
    ) -> None:
        """Graph should pause at human_approval for destructive actions."""
        for m in (mock_logs, mock_metrics, mock_change, mock_runbook):
            m.return_value = mock_analyst_llm
        mock_planner.return_value = mock_planner_llm_destructive

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-TEST-001"}}

        result = g.invoke(incident_state, config=config)

        assert result["status"] == IncidentStatus.AWAITING_APPROVAL
        assert len(result["proposed_actions"]) > 0
        assert result["proposed_actions"][0]["is_destructive"] is True

    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    @patch("incident_commander.agents.executor.get_llm")
    def test_hitl_resume_after_approval(
        self,
        mock_executor_llm_fn: MagicMock,
        mock_planner: MagicMock,
        mock_runbook: MagicMock,
        mock_change: MagicMock,
        mock_metrics: MagicMock,
        mock_logs: MagicMock,
        mock_analyst_llm: MagicMock,
        mock_planner_llm_destructive: MagicMock,
        incident_state: dict,
        checkpointer: Any,
    ) -> None:
        """After approval via update_state, graph should resume and resolve."""
        for m in (mock_logs, mock_metrics, mock_change, mock_runbook):
            m.return_value = mock_analyst_llm
        mock_planner.return_value = mock_planner_llm_destructive

        executor_mock = MagicMock()
        executor_mock.bind_tools.return_value = executor_mock
        executor_mock.invoke.return_value = _ai_msg({
            "action_taken": "Rolled back payments-svc",
            "tool_called": "rollback_to_previous_version",
            "success": True,
            "result_summary": "Rollback succeeded.",
            "next_step": "monitor",
        })
        mock_executor_llm_fn.return_value = executor_mock

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-TEST-HITL"}}

        # First run — pauses at HITL
        incident_state["incident_id"] = "INC-TEST-HITL"
        g.invoke(incident_state, config=config)

        # Simulate human approval — inject approved_action
        snapshot = g.get_state(config)
        proposed = snapshot.values.get("proposed_actions", [])
        assert len(proposed) > 0

        g.update_state(
            config,
            {
                "approved_action": proposed[0],
                "approval_notes": "Approved by on-call.",
                "status": IncidentStatus.REMEDIATING,
            },
        )

        # Resume from checkpoint
        final = g.invoke(None, config=config)

        assert final["status"] == IncidentStatus.RESOLVED
        assert final["execution_result"]["success"] is True

    @patch("incident_commander.agents.executor.get_llm")
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    def test_audit_trail_accumulates(
        self,
        mock_planner: MagicMock,
        mock_runbook: MagicMock,
        mock_change: MagicMock,
        mock_metrics: MagicMock,
        mock_logs: MagicMock,
        mock_executor_fn: MagicMock,
        mock_analyst_llm: MagicMock,
        mock_planner_llm_safe: MagicMock,
        checkpointer: Any,
    ) -> None:
        """Audit trail should have entries from every node that ran."""
        for m in (mock_logs, mock_metrics, mock_change, mock_runbook):
            m.return_value = mock_analyst_llm
        mock_planner.return_value = mock_planner_llm_safe
        exec_mock = MagicMock()
        exec_bound = MagicMock()
        exec_mock.bind_tools.return_value = exec_bound
        exec_bound.invoke.return_value = _ai_msg({
            "action_taken": "Monitored service",
            "tool_called": "none",
            "success": True,
            "result_summary": "Monitoring complete.",
            "next_step": "resolve",
        })
        mock_executor_fn.return_value = exec_mock

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-AUDIT"}}

        state = initial_state(
            incident_id="INC-AUDIT",
            title="Test audit trail",
            description="Testing that audit trail accumulates across nodes",
            severity=IncidentSeverity.LOW,
            affected_service="api",
        )

        result = g.invoke(state, config=config)
        assert len(result["audit_trail"]) >= 3  # supervisor + analysts + planner
        agents = {entry["agent"] for entry in result["audit_trail"]}
        assert "supervisor" in agents
        assert "planner" in agents

    @patch("incident_commander.agents.executor.get_llm")
    @patch("incident_commander.agents.log_analyst.get_llm")
    @patch("incident_commander.agents.metrics_analyst.get_llm")
    @patch("incident_commander.agents.change_analyst.get_llm")
    @patch("incident_commander.agents.runbook_retriever.get_llm")
    @patch("incident_commander.agents.planner.get_llm")
    def test_all_four_analysts_contribute_findings(
        self,
        mock_planner: MagicMock,
        mock_runbook: MagicMock,
        mock_change: MagicMock,
        mock_metrics: MagicMock,
        mock_logs: MagicMock,
        mock_executor_fn: MagicMock,
        mock_analyst_llm: MagicMock,
        mock_planner_llm_safe: MagicMock,
        checkpointer: Any,
    ) -> None:
        """All four specialist analysts should write findings to state."""
        for m in (mock_logs, mock_metrics, mock_change, mock_runbook):
            m.return_value = mock_analyst_llm
        mock_planner.return_value = mock_planner_llm_safe
        exec_mock2 = MagicMock()
        exec_bound2 = MagicMock()
        exec_mock2.bind_tools.return_value = exec_bound2
        exec_bound2.invoke.return_value = _ai_msg({
            "action_taken": "Monitored",
            "tool_called": "none",
            "success": True,
            "result_summary": "Done.",
            "next_step": "resolve",
        })
        mock_executor_fn.return_value = exec_mock2

        g = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "INC-PARALLEL"}}

        state = initial_state(
            incident_id="INC-PARALLEL",
            title="Parallel analyst test",
            description="Testing parallel investigation",
            severity=IncidentSeverity.HIGH,
            affected_service="checkout-api",
        )

        result = g.invoke(state, config=config)

        assert len(result["log_findings"]) > 0
        assert len(result["metrics_findings"]) > 0
        assert len(result["change_findings"]) > 0
        assert len(result["runbook_findings"]) > 0
