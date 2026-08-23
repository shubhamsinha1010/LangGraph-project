"""Pydantic output models for every agent node.

Using .with_structured_output(Model) on the LLM ensures:
- Type-safe, validated output — no more manual JSON parsing
- Clear contracts between nodes that IDEs and type checkers understand
- Immediate failure on bad LLM output instead of silent corruption downstream
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Analyst outputs
# --------------------------------------------------------------------------- #

class LogAnalystOutput(BaseModel):
    findings: list[str] = Field(description="Concise findings, max 5 items")
    error_count: int = Field(default=0)
    error_rate_pct: float = Field(default=0.0)
    top_error: str = Field(default="")
    relevant_traces: list[str] = Field(default_factory=list)


class MetricsAnalystOutput(BaseModel):
    findings: list[str] = Field(description="Concise findings, max 5 items")
    p99_latency_ms: float = Field(default=0.0)
    error_rate_pct: float = Field(default=0.0)
    anomalies: list[str] = Field(default_factory=list)
    likely_cause_category: Literal[
        "traffic_spike", "resource_exhaustion", "code_regression", "unknown"
    ] = Field(default="unknown")


class ChangeAnalystOutput(BaseModel):
    findings: list[str] = Field(description="Concise findings, max 5 items")
    most_likely_culprit_change_id: str | None = Field(default=None)
    culprit_description: str = Field(default="")
    last_deploy_minutes_ago: int | None = Field(default=None)
    correlation_confidence: Literal["high", "medium", "low"] = Field(default="low")


class RunbookRetrieverOutput(BaseModel):
    findings: list[str] = Field(description="Concise findings, max 5 items")
    best_runbook_id: str = Field(default="")
    best_runbook_title: str = Field(default="")
    recommended_steps: list[str] = Field(default_factory=list)
    estimated_resolution_minutes: int = Field(default=0)


# --------------------------------------------------------------------------- #
#  Planner output
# --------------------------------------------------------------------------- #

class ProposedAction(BaseModel):
    action_type: Literal[
        "rollback", "restart", "scale", "config_change", "investigate_more", "escalate"
    ]
    description: str
    service: str
    is_destructive: bool
    priority: int = Field(ge=1, le=5)


class PlannerOutput(BaseModel):
    diagnosis: str = Field(description="2-3 sentence root cause summary")
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    needs_more_investigation: bool = Field(default=False)


# --------------------------------------------------------------------------- #
#  Executor output
# --------------------------------------------------------------------------- #

class ExecutorOutput(BaseModel):
    action_taken: str
    tool_called: str
    success: bool
    result_summary: str
    next_step: Literal["monitor", "escalate", "resolve"] = Field(default="monitor")
