"""Incident graph state definition.

Rules enforced here:
- Every field has an explicit reducer annotation or a default that makes the merge strategy obvious.
- Large blobs (log text, raw metrics) are stored by reference (summary strings) — not in full.
- Enums are used for all categorical fields so type-checkers catch bad string literals.
"""

import operator
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from incident_commander.core.constants import (
    IncidentSeverity,
    IncidentStatus,
    RoutingDecision,
)


def _merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reducer that merges two dicts — right wins on key collision."""
    return {**left, **right}


def _merge_findings(
    left: list[str], right: list[str]
) -> list[str]:
    """Reducer that appends new unique findings from parallel branches."""
    seen = set(left)
    return left + [f for f in right if f not in seen]


class IncidentState:
    """
    Shared state object flowing through the incident graph.

    LangGraph passes this dict-like object to every node.  Each node returns
    only the keys it wants to update; the runtime merges them using the
    reducer attached to each Annotated field.
    """

    # Required — set once by the caller, never mutated
    incident_id: str
    title: str
    description: str
    severity: IncidentSeverity
    affected_service: str
    alert_source: str

    # Mutable status
    status: IncidentStatus

    # Conversational messages — add_messages appends, never overwrites
    messages: Annotated[list[BaseMessage], add_messages]

    # Investigation findings from specialist agents — parallel-safe append reducer
    log_findings: Annotated[list[str], _merge_findings]
    metrics_findings: Annotated[list[str], _merge_findings]
    change_findings: Annotated[list[str], _merge_findings]
    runbook_findings: Annotated[list[str], _merge_findings]

    # Planner outputs
    diagnosis: str
    confidence: float
    proposed_actions: Annotated[list[dict[str, Any]], operator.add]

    # HITL approval
    approved_action: dict[str, Any] | None
    approval_notes: str

    # Execution result
    execution_result: dict[str, Any] | None

    # Routing metadata
    routing_decision: RoutingDecision | None
    investigation_cycles: int
    needs_more_investigation: bool

    # Audit trail — every node records what it did
    audit_trail: Annotated[list[dict[str, Any]], operator.add]


# TypedDict version used at runtime — IncidentState above is for documentation/IDE hints
from typing import TypedDict  # noqa: E402  (below class body intentionally)


class IncidentStateDict(TypedDict, total=False):
    incident_id: str
    title: str
    description: str
    severity: str
    affected_service: str
    alert_source: str
    status: str
    messages: Annotated[list[BaseMessage], add_messages]
    log_findings: Annotated[list[str], _merge_findings]
    metrics_findings: Annotated[list[str], _merge_findings]
    change_findings: Annotated[list[str], _merge_findings]
    runbook_findings: Annotated[list[str], _merge_findings]
    diagnosis: str
    confidence: float
    proposed_actions: Annotated[list[dict[str, Any]], operator.add]
    approved_action: dict[str, Any] | None
    approval_notes: str
    execution_result: dict[str, Any] | None
    routing_decision: str | None
    investigation_cycles: int
    needs_more_investigation: bool
    audit_trail: Annotated[list[dict[str, Any]], operator.add]


def initial_state(
    incident_id: str,
    title: str,
    description: str,
    severity: IncidentSeverity,
    affected_service: str,
    alert_source: str = "manual",
) -> IncidentStateDict:
    """Factory that returns a fully-populated initial state dict."""
    return IncidentStateDict(
        incident_id=incident_id,
        title=title,
        description=description,
        severity=severity,
        affected_service=affected_service,
        alert_source=alert_source,
        status=IncidentStatus.OPEN,
        messages=[],
        log_findings=[],
        metrics_findings=[],
        change_findings=[],
        runbook_findings=[],
        diagnosis="",
        confidence=0.0,
        proposed_actions=[],
        approved_action=None,
        approval_notes="",
        execution_result=None,
        routing_decision=None,
        investigation_cycles=0,
        needs_more_investigation=True,
        audit_trail=[],
    )
