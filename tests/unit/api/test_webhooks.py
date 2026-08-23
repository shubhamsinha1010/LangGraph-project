"""Tests for webhook intake and edit-plan endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from incident_commander.core.constants import IncidentSeverity, IncidentStatus
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import graph


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestPagerDutyWebhook:
    async def test_accepts_valid_payload(self, client: AsyncClient) -> None:
        payload = {
            "messages": [
                {
                    "incident": {
                        "id": "Q1234ABCDEF",
                        "title": "checkout-api: high error rate",
                        "urgency": "high",
                        "service": {"summary": "checkout-api", "id": "SVC001"},
                        "body": {"details": "Error rate spiked to 18%"},
                    }
                }
            ]
        }
        with patch("api.routes.webhooks._run_investigation", new_callable=AsyncMock):
            resp = await client.post("/api/v1/webhooks/pagerduty", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert len(data["incidents_created"]) == 1
        assert data["incidents_created"][0].startswith("PD-")

    async def test_accepts_empty_messages(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/webhooks/pagerduty", json={"messages": []})
        assert resp.status_code == 202
        assert resp.json()["incidents_created"] == []


class TestDatadogWebhook:
    async def test_accepts_datadog_payload(self, client: AsyncClient) -> None:
        payload = {
            "title": "High latency on payments-svc",
            "text": "p99 latency exceeded 2000ms threshold",
            "alert_type": "error",
            "service": "payments-svc",
            "host": "payments-worker-1",
            "alert_metric": "trace.http.request.duration",
            "tags": "env:prod,team:payments",
        }
        with patch("api.routes.webhooks._run_investigation", new_callable=AsyncMock):
            resp = await client.post("/api/v1/webhooks/datadog", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert data["incident_id"].startswith("DD-")

    async def test_severity_mapping_error_to_critical(self, client: AsyncClient) -> None:
        from api.schemas.webhook import DatadogWebhookPayload
        p = DatadogWebhookPayload(alert_type="error")
        assert p.severity == IncidentSeverity.CRITICAL

    async def test_severity_mapping_warning_to_high(self, client: AsyncClient) -> None:
        from api.schemas.webhook import DatadogWebhookPayload
        p = DatadogWebhookPayload(alert_type="warning")
        assert p.severity == IncidentSeverity.HIGH


class TestEditPlan:
    def _seed(self, incident_id: str) -> None:
        state = initial_state(
            incident_id=incident_id,
            title="Edit plan test",
            description="Testing plan edit",
            severity=IncidentSeverity.CRITICAL,
            affected_service="api",
        )
        state["status"] = IncidentStatus.AWAITING_APPROVAL
        state["proposed_actions"] = [
            {
                "action_type": "rollback",
                "description": "Rollback api to previous version",
                "service": "api",
                "is_destructive": True,
                "priority": 1,
            }
        ]
        graph.update_state({"configurable": {"thread_id": incident_id}}, state)

    async def test_edit_plan_updates_action(self, client: AsyncClient) -> None:
        self._seed("INC-EDIT-001")
        resp = await client.patch(
            "/api/v1/incidents/INC-EDIT-001/edit-plan",
            json={
                "action_index": 0,
                "updates": {"description": "Rollback api to v2.1.0 specifically"},
                "notes": "v2.1.1 introduced the bug",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_action"]["description"] == "Rollback api to v2.1.0 specifically"

    async def test_edit_plan_out_of_range_returns_400(self, client: AsyncClient) -> None:
        self._seed("INC-EDIT-002")
        resp = await client.patch(
            "/api/v1/incidents/INC-EDIT-002/edit-plan",
            json={"action_index": 99, "updates": {"description": "x"}},
        )
        assert resp.status_code == 400

    async def test_edit_plan_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/v1/incidents/GHOST/edit-plan",
            json={"action_index": 0, "updates": {}},
        )
        assert resp.status_code == 404
