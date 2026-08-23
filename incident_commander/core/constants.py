"""Domain-wide constants. Import from here — never hard-code values across the codebase."""

from enum import StrEnum


class IncidentSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    LOG_ANALYST = "log_analyst"
    METRICS_ANALYST = "metrics_analyst"
    CHANGE_ANALYST = "change_analyst"
    RUNBOOK_RETRIEVER = "runbook_retriever"
    PLANNER = "planner"
    EXECUTOR = "executor"


class RoutingDecision(StrEnum):
    INVESTIGATE = "investigate"
    PLAN = "plan"
    AWAIT_APPROVAL = "await_approval"
    EXECUTE = "execute"
    RESOLVE = "resolve"
    ESCALATE = "escalate"


# Graph node names — kept in constants to avoid magic strings across edge definitions
NODE_SUPERVISOR = "supervisor"
NODE_LOG_ANALYST = "log_analyst"
NODE_METRICS_ANALYST = "metrics_analyst"
NODE_CHANGE_ANALYST = "change_analyst"
NODE_RUNBOOK_RETRIEVER = "runbook_retriever"
NODE_PLANNER = "planner"
NODE_HUMAN_APPROVAL = "human_approval"
NODE_EXECUTOR = "executor"
NODE_RESOLVER = "resolver"

# LangGraph special nodes
START = "__start__"
END = "__end__"

# Confidence thresholds for routing
CONFIDENCE_THRESHOLD_PLAN = 0.7
CONFIDENCE_THRESHOLD_ESCALATE = 0.3

MAX_INVESTIGATION_CYCLES_DEFAULT = 5
