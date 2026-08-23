"""Webhook payload schemas for PagerDuty and Datadog alert ingestion."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from incident_commander.core.constants import IncidentSeverity


# --------------------------------------------------------------------------- #
#  PagerDuty
# --------------------------------------------------------------------------- #

class PagerDutyServiceReference(BaseModel):
    summary: str = Field(default="unknown-service")
    id: str = Field(default="")


class PagerDutyIncidentBody(BaseModel):
    id: str = Field(default="")
    title: str = Field(default="PagerDuty Alert")
    urgency: str = Field(default="low")  # "high" | "low"
    service: PagerDutyServiceReference = Field(default_factory=PagerDutyServiceReference)
    body: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}

    @property
    def severity(self) -> IncidentSeverity:
        return IncidentSeverity.CRITICAL if self.urgency == "high" else IncidentSeverity.MEDIUM

    @property
    def service_name(self) -> str:
        return self.service.summary or "unknown-service"

    @property
    def description(self) -> str:
        return self.body.get("details", self.title)


class PagerDutyWebhookPayload(BaseModel):
    """PagerDuty v3 webhook payload (messages array format)."""
    messages: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    def incidents(self) -> list[PagerDutyIncidentBody]:
        result = []
        for msg in self.messages:
            inc_data = msg.get("incident", {})
            if inc_data:
                result.append(PagerDutyIncidentBody(**inc_data))
        return result


# --------------------------------------------------------------------------- #
#  Datadog
# --------------------------------------------------------------------------- #

class DatadogWebhookPayload(BaseModel):
    """Datadog webhook payload (standard alert format)."""
    title: str = Field(default="Datadog Alert")
    text: str = Field(default="")
    alert_type: str = Field(default="info")  # "error" | "warning" | "info" | "success"
    alert_metric: str = Field(default="")
    host: str = Field(default="")
    tags: str = Field(default="")  # comma-separated
    service: str = Field(default="unknown-service")

    model_config = {"extra": "ignore"}

    @property
    def severity(self) -> IncidentSeverity:
        mapping = {
            "error": IncidentSeverity.CRITICAL,
            "warning": IncidentSeverity.HIGH,
            "info": IncidentSeverity.MEDIUM,
        }
        return mapping.get(self.alert_type, IncidentSeverity.LOW)

    @property
    def description(self) -> str:
        parts = [self.text]
        if self.alert_metric:
            parts.append(f"Metric: {self.alert_metric}")
        if self.host:
            parts.append(f"Host: {self.host}")
        return " | ".join(filter(None, parts))


# --------------------------------------------------------------------------- #
#  Edit-plan schema
# --------------------------------------------------------------------------- #

class EditPlanRequest(BaseModel):
    """Request to modify a proposed action before approval."""
    action_index: int = Field(default=0, ge=0, description="Index of the action to edit")
    updates: dict[str, Any] = Field(
        description="Fields to update on the action (e.g. version, description)"
    )
    notes: str = Field(default="", description="Reason for the edit")

    model_config = {
        "json_schema_extra": {
            "example": {
                "action_index": 0,
                "updates": {"description": "Rollback to v2.1.0 specifically", "version": "v2.1.0"},
                "notes": "v2.1.1 introduced the bug — want exact version",
            }
        }
    }
