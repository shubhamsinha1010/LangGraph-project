"""Incident Commander API routes — async throughout, SSE streaming.

Endpoints:
  POST   /incidents                     — create & stream investigation (SSE)
  GET    /incidents/{id}                — current incident state
  PATCH  /incidents/{id}/approve        — HITL approve + resume (SSE)
  GET    /incidents/{id}/history        — time-travel: every checkpoint step
  GET    /incidents/{id}/stream/tokens  — token-level streaming (messages mode)
  DELETE /incidents/{id}               — close an incident
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from api.schemas.incident import (
    ApproveActionRequest,
    CreateIncidentRequest,
    IncidentStatusResponse,
)
from incident_commander.core.config import get_settings
from incident_commander.core.constants import IncidentStatus
from incident_commander.core.exceptions import IncidentNotFoundError
from incident_commander.core.logging import get_logger
from incident_commander.core.state import initial_state
from incident_commander.graphs.supervisor import graph

router = APIRouter(prefix="/incidents", tags=["incidents"])
logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _config(incident_id: str) -> dict[str, Any]:
    settings = get_settings()
    return {
        "configurable": {"thread_id": incident_id},
        "recursion_limit": settings.max_investigation_cycles * 12,
    }


async def _get_state(incident_id: str) -> dict[str, Any]:
    snapshot = graph.get_state(_config(incident_id))
    if snapshot is None or not snapshot.values:
        raise IncidentNotFoundError(incident_id)
    return snapshot.values


async def _state_event_stream(
    incident_id: str,
    input_state: dict[str, Any] | None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield SSE state-update events from the graph."""
    config = _config(incident_id)
    async for event in graph.astream(input_state, config=config, stream_mode="values"):
        yield {
            "event": "state_update",
            "data": json.dumps({
                "incident_id": incident_id,
                "status": event.get("status"),
                "routing_decision": event.get("routing_decision"),
                "diagnosis": event.get("diagnosis", ""),
                "confidence": event.get("confidence", 0.0),
                "proposed_actions": event.get("proposed_actions", []),
                "investigation_cycles": event.get("investigation_cycles", 0),
            }),
        }
    yield {"event": "done", "data": json.dumps({"incident_id": incident_id})}


async def _token_stream(
    incident_id: str,
    input_state: dict[str, Any] | None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield token-level SSE events using LangGraph messages stream mode.

    This lets a frontend show the planner's diagnosis forming word-by-word,
    exactly like ChatGPT streaming — not just state snapshots.
    """
    config = _config(incident_id)
    async for event_type, event_data in graph.astream(
        input_state, config=config, stream_mode="messages"
    ):
        if event_type == "messages":
            for msg, meta in event_data:
                content = getattr(msg, "content", "")
                if content:
                    yield {
                        "event": "token",
                        "data": json.dumps({
                            "incident_id": incident_id,
                            "node": meta.get("langgraph_node", ""),
                            "content": content,
                        }),
                    }
    yield {"event": "done", "data": json.dumps({"incident_id": incident_id})}


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_incident(body: CreateIncidentRequest) -> EventSourceResponse:
    """Start an incident investigation. Streams state updates as SSE."""
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
        _state_event_stream(incident_id, input_state=state),
        headers={"X-Incident-ID": incident_id},
    )


@router.get("/{incident_id}", response_model=IncidentStatusResponse)
async def get_incident(incident_id: str) -> IncidentStatusResponse:
    """Retrieve the current state of an incident."""
    try:
        state = await _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")

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

    HITL resume pattern:
      1. Validates the action index against current state.
      2. Injects approved_action into the checkpoint via update_state().
      3. Re-invokes the graph (input=None) — resumes from the checkpoint.
      4. Streams state updates as SSE until the graph terminates.
    """
    try:
        state = await _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")

    proposed_actions = state.get("proposed_actions", [])
    if body.action_index >= len(proposed_actions):
        raise HTTPException(
            status_code=400,
            detail=(
                f"action_index {body.action_index} out of range. "
                f"{len(proposed_actions)} actions available (0-indexed)."
            ),
        )

    approved_action = proposed_actions[body.action_index]
    config = _config(incident_id)

    logger.info(
        "incident.approved",
        incident_id=incident_id,
        action=approved_action.get("action_type"),
        notes=body.notes,
    )

    graph.update_state(
        config,
        {
            "approved_action": approved_action,
            "approval_notes": body.notes,
            "status": IncidentStatus.REMEDIATING,
        },
    )

    return EventSourceResponse(
        _state_event_stream(incident_id, input_state=None),
    )


@router.get("/{incident_id}/history")
async def get_incident_history(incident_id: str) -> list[dict[str, Any]]:
    """Return the full time-travel history of an incident — every checkpoint.

    Each entry represents a superstep: which node ran, what state looked like
    after it, and when it happened. This directly demonstrates LangGraph's
    durable checkpointing — every step is persisted and inspectable.
    """
    config = _config(incident_id)
    history: list[dict[str, Any]] = []

    try:
        for snapshot in graph.get_state_history(config):
            values = snapshot.values or {}
            history.append({
                "step": len(history),
                "node": snapshot.next[0] if snapshot.next else "END",
                "timestamp": values.get("audit_trail", [{}])[-1].get("timestamp", ""),
                "status": values.get("status", ""),
                "routing_decision": values.get("routing_decision", ""),
                "investigation_cycles": values.get("investigation_cycles", 0),
                "diagnosis": values.get("diagnosis", ""),
                "confidence": values.get("confidence", 0.0),
                "findings_count": (
                    len(values.get("log_findings", []))
                    + len(values.get("metrics_findings", []))
                    + len(values.get("change_findings", []))
                    + len(values.get("runbook_findings", []))
                ),
                "audit_events": len(values.get("audit_trail", [])),
            })
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Incident history not found: {exc}")

    if not history:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")

    return list(reversed(history))  # chronological order


@router.get("/{incident_id}/stream/tokens")
async def stream_tokens(incident_id: str) -> EventSourceResponse:
    """Stream token-level output from an in-progress incident investigation.

    Unlike the state-snapshot stream, this yields individual tokens as the
    LLM produces them — enabling real-time word-by-word display in a frontend.
    Only useful while the graph is actively running.
    """
    return EventSourceResponse(
        _token_stream(incident_id, input_state=None),
    )


@router.delete("/{incident_id}", status_code=200)
async def close_incident(incident_id: str) -> dict[str, str]:
    """Close an incident without executing any action."""
    try:
        await _get_state(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=404, detail="Incident not found.")

    graph.update_state(_config(incident_id), {"status": IncidentStatus.CLOSED})
    logger.info("incident.closed", incident_id=incident_id)
    return {"incident_id": incident_id, "status": IncidentStatus.CLOSED}
