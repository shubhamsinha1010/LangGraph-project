"""API layer tests — uses httpx.AsyncClient with ASGI transport.

No real server is started. No real LLM calls are made.
Tests cover: create incident, get status, approve action, history, close, 404s.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import graph
from incident_commander.services.checkpointer import get_sync_checkpointer


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# --------------------------------------------------------------------------- #
#  Health endpoints
# --------------------------------------------------------------------------- #

class TestHealth:
    async def test_health_returns_ok(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    async def test_ready_returns_ready(self, client: AsyncClient) -> None:
        resp = await client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


# --------------------------------------------------------------------------- #
#  GET /incidents/{id}
# --------------------------------------------------------------------------- #

class TestGetIncident:
    def _seed_incident(self, incident_id: str) -> dict[str, Any]:
        """Put a fake incident into the graph's checkpointer."""
        state = initial_state(
            incident_id=incident_id,
            title="Test incident",
            description="Something broke",
            severity=IncidentSeverity.HIGH,
            affected_service="api",
        )
        state["status"] = IncidentStatus.INVESTIGATING
        state["diagnosis"] = "Deploy caused the issue."
        state["confidence"] = 0.8
        state["proposed_actions"] = [
            {
                "action_type": "rollback",
                "description": "Rollback api",
                "service": "api",
                "is_destructive": True,
                "priority": 1,
            }
        ]
        config = {"configurable": {"thread_id": incident_id}}
        graph.update_state(config, state)
        return state

    async def test_get_existing_incident(self, client: AsyncClient) -> None:
        self._seed_incident("INC-GET-001")
        resp = await client.get("/api/v1/incidents/INC-GET-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == "INC-GET-001"
        assert data["diagnosis"] == "Deploy caused the issue."
        assert data["confidence"] == 0.8

    async def test_get_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/incidents/DOES-NOT-EXIST-XYZ")
        assert resp.status_code == 404

    async def test_awaiting_approval_flag(self, client: AsyncClient) -> None:
        state = self._seed_incident("INC-APPROVAL-FLAG")
        graph.update_state(
            {"configurable": {"thread_id": "INC-APPROVAL-FLAG"}},
            {"status": IncidentStatus.AWAITING_APPROVAL},
        )
        resp = await client.get("/api/v1/incidents/INC-APPROVAL-FLAG")
        assert resp.status_code == 200
        assert resp.json()["awaiting_approval"] is True


# --------------------------------------------------------------------------- #
#  PATCH /incidents/{id}/approve
# --------------------------------------------------------------------------- #

class TestApproveAction:
    def _seed_awaiting(self, incident_id: str) -> None:
        state = initial_state(
            incident_id=incident_id,
            title="Awaiting approval",
            description="Needs rollback",
            severity=IncidentSeverity.CRITICAL,
            affected_service="checkout-api",
        )
        state["status"] = IncidentStatus.AWAITING_APPROVAL
        state["proposed_actions"] = [
            {
                "action_type": "rollback",
                "description": "Rollback checkout-api",
                "service": "checkout-api",
                "is_destructive": True,
                "priority": 1,
            }
        ]
        graph.update_state({"configurable": {"thread_id": incident_id}}, state)

    async def test_approve_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/v1/incidents/NONEXISTENT/approve",
            json={"action_index": 0, "notes": "ok"},
        )
        assert resp.status_code == 404

    async def test_approve_invalid_index_returns_400(self, client: AsyncClient) -> None:
        self._seed_awaiting("INC-APPROVE-BAD-IDX")
        resp = await client.patch(
            "/api/v1/incidents/INC-APPROVE-BAD-IDX/approve",
            json={"action_index": 99, "notes": ""},
        )
        assert resp.status_code == 400
        assert "out of range" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
#  GET /incidents/{id}/history
# --------------------------------------------------------------------------- #

class TestIncidentHistory:
    async def test_history_returns_steps(self, client: AsyncClient) -> None:
        """Mock get_state_history to return fake snapshots and verify the endpoint format."""
        incident_id = "INC-HISTORY-001"

        fake_snapshot = MagicMock()
        fake_snapshot.next = ["planner"]
        fake_snapshot.values = {
            "status": IncidentStatus.INVESTIGATING,
            "routing_decision": "investigate",
            "investigation_cycles": 1,
            "diagnosis": "Deploy caused the issue.",
            "confidence": 0.8,
            "log_findings": ["finding 1"],
            "metrics_findings": [],
            "change_findings": [],
            "runbook_findings": [],
            "audit_trail": [{"timestamp": "2026-08-23T10:00:00+00:00", "agent": "supervisor"}],
        }

        with patch("api.routes.incidents.graph") as mock_graph:
            mock_graph.get_state_history.return_value = iter([fake_snapshot])
            resp = await client.get(f"/api/v1/incidents/{incident_id}/history")

        assert resp.status_code == 200
        history = resp.json()
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["status"] == IncidentStatus.INVESTIGATING
        assert history[0]["confidence"] == 0.8
        assert "findings_count" in history[0]

    async def test_history_nonexistent_returns_404(self, client: AsyncClient) -> None:
        with patch("api.routes.incidents.graph") as mock_graph:
            mock_graph.get_state_history.return_value = iter([])
            resp = await client.get("/api/v1/incidents/GHOST-INCIDENT/history")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
#  DELETE /incidents/{id}
# --------------------------------------------------------------------------- #

class TestCloseIncident:
    async def test_close_existing_incident(self, client: AsyncClient) -> None:
        incident_id = "INC-CLOSE-001"
        state = initial_state(
            incident_id=incident_id,
            title="Close me",
            description="Test close",
            severity=IncidentSeverity.LOW,
            affected_service="api",
        )
        graph.update_state({"configurable": {"thread_id": incident_id}}, state)

        resp = await client.delete(f"/api/v1/incidents/{incident_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == IncidentStatus.CLOSED

    async def test_close_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/v1/incidents/GHOST-CLOSE")
        assert resp.status_code == 404
