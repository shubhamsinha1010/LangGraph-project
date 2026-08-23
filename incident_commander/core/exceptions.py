"""Domain exceptions. Every failure surface has a typed exception — never raise bare RuntimeError."""


class IncidentCommanderError(Exception):
    """Base exception for all domain errors."""


class IncidentNotFoundError(IncidentCommanderError):
    """Raised when a thread_id does not correspond to any known incident."""


class ApprovalRequiredError(IncidentCommanderError):
    """Raised when a destructive action is attempted without prior approval."""

    def __init__(self, action: str, incident_id: str) -> None:
        self.action = action
        self.incident_id = incident_id
        super().__init__(
            f"Action '{action}' on incident '{incident_id}' requires human approval."
        )


class ToolExecutionError(IncidentCommanderError):
    """Raised when a tool call fails after all retries are exhausted."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {reason}")


class CheckpointError(IncidentCommanderError):
    """Raised when checkpointer cannot save or load state."""


class LLMError(IncidentCommanderError):
    """Raised when the LLM backend returns an unrecoverable error."""


class MaxCyclesExceededError(IncidentCommanderError):
    """Raised when investigation cycles exceed the configured limit."""

    def __init__(self, cycles: int) -> None:
        super().__init__(
            f"Investigation exceeded maximum allowed cycles ({cycles}). Escalating to human."
        )


class RollbackError(IncidentCommanderError):
    """Raised when a rollback operation fails."""

    def __init__(self, service: str, reason: str) -> None:
        self.service = service
        super().__init__(f"Rollback of '{service}' failed: {reason}")
