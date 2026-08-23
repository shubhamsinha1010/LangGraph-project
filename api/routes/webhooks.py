"""Webhook intake endpoints for PagerDuty and Datadog.

These endpoints accept real alert payloads, parse them into the incident
domain model, and kick off an investigation automatically — no manual
POST /incidents needed.

Production usage:
  - Point your PagerDuty outbound webhook at POST /api/v1/webhooks/pagerduty
  - Point your Datadog webhook integration at POST /api/v1/webhooks/datadog
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse

from api.schemas.webhook import DatadogWebhookPayload, PagerDutyWebhookPayload
from incident_commander.core.logging import get_logger
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import graph
from incident_commander.services.checkpointer import get_sync_checkpointer

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


def _config(incident_id: str) -> dict[str, Any]:
    from incident_commander.core.config import get_settings
    settings = get_settings()
    return {
        "configurable": {"thread_id": incident_id},
        "recursion_limit": settings.max_investigation_cycles * 12,
    }


async def _run_investigation(state: dict[str, Any], incident_id: str) -> None:
    """Run the graph in the background — fire-and-forget from webhook handler."""
    config = _config(incident_id)
    try:
        await graph.ainvoke(state, config=config)
        logger.info("webhook.investigation_complete", incident_id=incident_id)
    except Exception as exc:
        logger.error("webhook.investigation_failed", incident_id=incident_id, error=str(exc))


@router.post("/pagerduty", status_code=status.HTTP_202_ACCEPTED)
async def pagerduty_webhook(
    payload: PagerDutyWebhookPayload,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Accept a PagerDuty v3 webhook and start an incident for each alert.

    PagerDuty config:
      - Webhook type: v3
      - Events: incident.triggered, incident.acknowledged
      - URL: https://your-host/api/v1/webhooks/pagerduty
    """
    incidents_created = []
    for inc in payload.incidents():
        incident_id = f"PD-{inc.id or uuid.uuid4().hex[:8]}"
        state = initial_state(
            incident_id=incident_id,
            title=inc.title,
            description=inc.description,
            severity=inc.severity,
            affected_service=inc.service_name,
            alert_source="pagerduty",
        )
        background_tasks.add_task(_run_investigation, state, incident_id)
        incidents_created.append(incident_id)
        logger.info("webhook.pagerduty.incident_created", incident_id=incident_id, service=inc.service_name)

    return JSONResponse(
        status_code=202,
        content={"accepted": True, "incidents_created": incidents_created},
    )


@router.post("/datadog", status_code=status.HTTP_202_ACCEPTED)
async def datadog_webhook(
    payload: DatadogWebhookPayload,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Accept a Datadog webhook alert and start an incident investigation.

    Datadog config:
      - Integration: Webhooks
      - URL: https://your-host/api/v1/webhooks/datadog
      - Payload: use the default Datadog webhook JSON format
    """
    incident_id = f"DD-{uuid.uuid4().hex[:8]}"
    state = initial_state(
        incident_id=incident_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        affected_service=payload.service or payload.host or "unknown-service",
        alert_source="datadog",
    )
    background_tasks.add_task(_run_investigation, state, incident_id)
    logger.info("webhook.datadog.incident_created", incident_id=incident_id, title=payload.title)

    return JSONResponse(
        status_code=202,
        content={"accepted": True, "incident_id": incident_id},
    )
