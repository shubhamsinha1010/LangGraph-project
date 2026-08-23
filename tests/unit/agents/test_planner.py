"""Unit tests for the planner node — mocks the LLM, uses structured output."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from incident_commander.core.constants import IncidentSeverity, RoutingDecision
from incident_commander.core.output_models import PlannerOutput, ProposedAction


@pytest.fixture()
def investigating_state() -> dict:
    return {
        "incident_id": "INC-001",
        "title": "checkout-api error spike",
        "description": "High error rate after deploy",
        "severity": IncidentSeverity.CRITICAL,
        "affected_service": "checkout-api",
        "log_findings": ["Error rate 18%", "Connection pool exhausted"],
        "metrics_findings": ["p99 2400ms — 3x baseline"],
        "change_findings": ["Deploy 15 min ago — high risk"],
        "runbook_findings": ["Rollback recommended"],
        "investigation_cycles": 1,
    }


def _planner_llm_mock(output: PlannerOutput) -> MagicMock:
    m = MagicMock()
    m.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    return m


class TestPlannerNode:
    @patch("incident_commander.agents.planner.get_llm")
    async def test_returns_diagnosis_and_actions(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        from incident_commander.agents.planner import planner_node

        mock_get_llm.return_value = _planner_llm_mock(
            PlannerOutput(
                diagnosis="Recent deploy caused connection pool exhaustion.",
                confidence=0.85,
                proposed_actions=[
                    ProposedAction(
                        action_type="rollback",
                        description="Rollback checkout-api",
                        service="checkout-api",
                        is_destructive=True,
                        priority=1,
                    )
                ],
                needs_more_investigation=False,
            )
        )

        result = await planner_node(investigating_state)

        assert result["diagnosis"] == "Recent deploy caused connection pool exhaustion."
        assert result["confidence"] == 0.85
        assert len(result["proposed_actions"]) == 1
        assert result["proposed_actions"][0]["action_type"] == "rollback"
        assert result["needs_more_investigation"] is False

    @patch("incident_commander.agents.planner.get_llm")
    async def test_destructive_action_sets_await_approval(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        from incident_commander.agents.planner import planner_node

        mock_get_llm.return_value = _planner_llm_mock(
            PlannerOutput(
                diagnosis="Deploy caused issue.",
                confidence=0.9,
                proposed_actions=[
                    ProposedAction(
                        action_type="rollback",
                        description="Rollback",
                        service="api",
                        is_destructive=True,
                        priority=1,
                    )
                ],
                needs_more_investigation=False,
            )
        )

        result = await planner_node(investigating_state)
        assert result["routing_decision"] == RoutingDecision.AWAIT_APPROVAL
        assert result["approved_action"] is None

    @patch("incident_commander.agents.planner.get_llm")
    async def test_low_confidence_triggers_more_investigation(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        from incident_commander.agents.planner import planner_node

        mock_get_llm.return_value = _planner_llm_mock(
            PlannerOutput(
                diagnosis="Unclear root cause.",
                confidence=0.3,
                proposed_actions=[],
                needs_more_investigation=True,
            )
        )

        result = await planner_node(investigating_state)
        assert result["needs_more_investigation"] is True
        assert result["routing_decision"] == RoutingDecision.INVESTIGATE

    @patch("incident_commander.agents.planner.get_llm")
    async def test_non_destructive_action_auto_approved(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        from incident_commander.agents.planner import planner_node

        mock_get_llm.return_value = _planner_llm_mock(
            PlannerOutput(
                diagnosis="Traffic spike, no code change needed.",
                confidence=0.9,
                proposed_actions=[
                    ProposedAction(
                        action_type="investigate_more",
                        description="Monitor for 5 min",
                        service="api",
                        is_destructive=False,
                        priority=1,
                    )
                ],
                needs_more_investigation=False,
            )
        )

        result = await planner_node(investigating_state)
        assert result["routing_decision"] == RoutingDecision.EXECUTE
        assert result["approved_action"] is not None

    @patch("incident_commander.agents.planner.get_llm")
    async def test_audit_trail_includes_planner_entry(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        from incident_commander.agents.planner import planner_node

        mock_get_llm.return_value = _planner_llm_mock(
            PlannerOutput(
                diagnosis="Test.", confidence=0.8,
                proposed_actions=[], needs_more_investigation=False,
            )
        )

        result = await planner_node(investigating_state)
        assert len(result["audit_trail"]) == 1
        assert result["audit_trail"][0]["agent"] == "planner"
