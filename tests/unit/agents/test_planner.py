"""Unit tests for the planner node — mocks the LLM so no API key is needed."""

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from incident_commander.agents.planner import planner_node
from incident_commander.core.constants import IncidentSeverity, RoutingDecision


def _make_ai_message(payload: dict) -> AIMessage:
    return AIMessage(content=json.dumps(payload))


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
        "runbook_findings": ["Runbook: rollback recommended"],
        "investigation_cycles": 1,
    }


class TestPlannerNode:
    @patch("incident_commander.agents.planner.get_llm")
    def test_returns_diagnosis_and_actions(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_ai_message({
            "diagnosis": "Recent deploy caused connection pool exhaustion.",
            "confidence": 0.85,
            "proposed_actions": [
                {
                    "action_type": "rollback",
                    "description": "Rollback checkout-api",
                    "service": "checkout-api",
                    "is_destructive": True,
                    "priority": 1,
                }
            ],
            "needs_more_investigation": False,
        })
        mock_get_llm.return_value = mock_llm

        result = planner_node(investigating_state)

        assert result["diagnosis"] == "Recent deploy caused connection pool exhaustion."
        assert result["confidence"] == 0.85
        assert len(result["proposed_actions"]) == 1
        assert result["proposed_actions"][0]["action_type"] == "rollback"
        assert result["needs_more_investigation"] is False

    @patch("incident_commander.agents.planner.get_llm")
    def test_destructive_action_sets_await_approval(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_ai_message({
            "diagnosis": "Deploy caused issue.",
            "confidence": 0.9,
            "proposed_actions": [
                {
                    "action_type": "rollback",
                    "description": "Rollback",
                    "service": "api",
                    "is_destructive": True,
                    "priority": 1,
                }
            ],
            "needs_more_investigation": False,
        })
        mock_get_llm.return_value = mock_llm

        result = planner_node(investigating_state)
        assert result["routing_decision"] == RoutingDecision.AWAIT_APPROVAL

    @patch("incident_commander.agents.planner.get_llm")
    def test_low_confidence_triggers_more_investigation(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_ai_message({
            "diagnosis": "Unclear root cause.",
            "confidence": 0.3,
            "proposed_actions": [],
            "needs_more_investigation": True,
        })
        mock_get_llm.return_value = mock_llm

        result = planner_node(investigating_state)
        assert result["needs_more_investigation"] is True
        assert result["routing_decision"] == RoutingDecision.INVESTIGATE

    @patch("incident_commander.agents.planner.get_llm")
    def test_audit_trail_includes_planner_entry(
        self, mock_get_llm: MagicMock, investigating_state: dict
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_ai_message({
            "diagnosis": "Test.",
            "confidence": 0.8,
            "proposed_actions": [],
            "needs_more_investigation": False,
        })
        mock_get_llm.return_value = mock_llm

        result = planner_node(investigating_state)
        assert len(result["audit_trail"]) == 1
        assert result["audit_trail"][0]["agent"] == "planner"
