"""Incident Commander API routes.

Endpoints:
  POST   /incidents               — create & start an incident (streaming SSE)
  GET    /incidents/{id}          — get current incident state
  PATCH  /incidents/{id}/approve  — submit human approval and resume execution
  GET    /incidents/{id}/stream   — stream graph events for an existing incident
"""

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from api.schemas.incident import (
    ApproveActionRequest,
    CreateIncidentRequest,
    IncidentResponse,
    IncidentStatusResponse,
)
from incident_commander.core.constants import IncidentStatus
from incident_commander.core.exceptions import (
    ApprovalRequiredError,
    IncidentNotFoundError,
)
from incident_commander.core.logging import get_logger
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import graph

router = APIRouter(prefix="/incidents", tags=["incidents"])
logger = get_logger(__name__)


def _make_config(incident_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": incident_id}}


def _get_state(incident_id: str) -> dict[str, Any]:
    """Retrieve the current graph state for an incident thread."""
    try:
        snapshot = graph.get_state(_make_config(incident_id))
        if snapshot is None or not snapshot.values:
            raise IncidentNotFoundError(incident_id)
        return snapshot.values
    except Exception as exc:
        if isinstance(exc, IncidentNotFoundError):
            raise
        raise IncidentNotFoundError(incident_id) from exc


async def _stream_graph_events(
    incident_id: str, input_state: dict[str, Any] | None = None
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield SSE-compatible event dicts from the graph stream."""
    config = _make_config(incident_id)
    stream_input = input_state if input_state is not None else None

    async for event in graph.astream(
        stream_input,
        config=config,
        stream_mode="values",
    ):
        yield {
            "event": "state_update",
            "data": json.dumps(
                {
                    "incident_id": incident_id,
                    "status": event.get("status"),
                    "routing_decision": event.get("routing_decision"),
                    "diagnosis": event.get("diagnosis", ""),
                    "confidence": event.get("confidence", 0.0),
                    "proposed_actions": event.get("proposed_actions", []),
                    "investigation_cycles": event.get("investigation_cycles", 0),
                }
            ),
        }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_incident(body: CreateIncidentRequest) -> EventSourceResponse:
    """Start an incident investigation.  Returns an SSE stream of state updates."""
    incident_id = str(uuid.uuid4())
    logger.info("incident.created", incident_id=incident_id, title=body.title)

    state = initial_state(
        incident_id=incident_id,
        title=body.title,
        description=body.description,
        severity=body.severity,
        affected_service=body.affected_service,
        alert_source=body.alert_source,
    )

    return EventSourceResponse(
        _stream_graph_events(incident_id, input_state=state),
        headers={"X-Incident-ID": incident_id},
    )


@router.get("/{incident_id}", response_model=IncidentStatusResponse)
async def get_incident(incident_id: str) -> IncidentStatusResponse:
    """Retrieve the current state of an incident."""
    try:
        state = _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    return IncidentStatusResponse(
        incident_id=incident_id,
        status=state.get("status", IncidentStatus.OPEN),
        awaiting_approval=state.get("status") == IncidentStatus.AWAITING_APPROVAL,
        proposed_actions=state.get("proposed_actions", []),
        diagnosis=state.get("diagnosis", ""),
        confidence=state.get("confidence", 0.0),
    )


@router.patch("/{incident_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve_action(
    incident_id: str, body: ApproveActionRequest
) -> EventSourceResponse:
    """Submit human approval for a proposed action and resume execution.

    This is the HITL resume endpoint:
    1. Fetches current state to validate the action index.
    2. Calls graph.update_state() to inject the approved_action.
    3. Re-invokes the graph from the checkpoint — it resumes from the
       human_approval node and continues to executor → resolve.
    """
    try:
        state = _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    proposed_actions = state.get("proposed_actions", [])
    if body.action_index >= len(proposed_actions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"action_index {body.action_index} is out of range. "
                f"There are {len(proposed_actions)} proposed actions (0-indexed)."
            ),
        )

    approved_action = proposed_actions[body.action_index]
    config = _make_config(incident_id)

    logger.info(
        "incident.approved",
        incident_id=incident_id,
        action=approved_action.get("action_type"),
        engineer_notes=body.notes,
    )

    # Inject the approved action into the checkpoint — this is the LangGraph
    # update_state() pattern for HITL resume
    graph.update_state(
        config,
        {
            "approved_action": approved_action,
            "approval_notes": body.notes,
            "status": IncidentStatus.REMEDIATING,
        },
    )

    # Resume from checkpoint — pass None so LangGraph reads from checkpointer
    return EventSourceResponse(
        _stream_graph_events(incident_id, input_state=None),
    )


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_200_OK,
    summary="Mark an incident closed",
)
async def close_incident(incident_id: str) -> dict[str, str]:
    """Close an incident without executing any action."""
    try:
        state = _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=404, detail="Incident not found.")

    config = _make_config(incident_id)
    graph.update_state(config, {"status": IncidentStatus.CLOSED})
    logger.info("incident.closed", incident_id=incident_id)
    return {"incident_id": incident_id, "status": IncidentStatus.CLOSED}
