"""Request and response schemas for the Incident Commander API."""

from typing import Any

from pydantic import BaseModel, Field

from incident_commander.core.constants import IncidentSeverity, IncidentStatus


class CreateIncidentRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=200, description="Short incident title")
    description: str = Field(..., min_length=10, description="Full incident description")
    severity: IncidentSeverity = Field(default=IncidentSeverity.HIGH)
    affected_service: str = Field(..., min_length=1, description="Name of the affected service")
    alert_source: str = Field(default="manual", description="e.g. pagerduty, datadog, manual")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "checkout-api: high error rate (18%)",
                "description": "checkout-api p99 latency spiked to 2.4s and error rate is 18%. Payments are failing.",
                "severity": "critical",
                "affected_service": "checkout-api",
                "alert_source": "datadog",
            }
        }
    }


class ApproveActionRequest(BaseModel):
    action_index: int = Field(
        default=0,
        ge=0,
        description="Index of the proposed_actions list to approve",
    )
    notes: str = Field(default="", description="Optional approval notes from the engineer")

    model_config = {
        "json_schema_extra": {
            "example": {"action_index": 0, "notes": "Looks good, proceed with rollback."}
        }
    }


class IncidentResponse(BaseModel):
    incident_id: str
    title: str
    status: str
    severity: str
    affected_service: str
    diagnosis: str
    confidence: float
    proposed_actions: list[dict[str, Any]]
    execution_result: dict[str, Any] | None
    investigation_cycles: int
    audit_trail: list[dict[str, Any]]


class IncidentStatusResponse(BaseModel):
    incident_id: str
    status: str
    awaiting_approval: bool
    proposed_actions: list[dict[str, Any]]
    diagnosis: str
    confidence: float
