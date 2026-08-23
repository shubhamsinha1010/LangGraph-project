"""Unit tests for domain exceptions."""

import pytest

from incident_commander.core.exceptions import (
    ApprovalRequiredError,
    IncidentCommanderError,
    MaxCyclesExceededError,
    RollbackError,
    ToolExecutionError,
)


class TestApprovalRequiredError:
    def test_message_includes_action_and_incident(self) -> None:
        exc = ApprovalRequiredError("rollback", "INC-001")
        assert "rollback" in str(exc)
        assert "INC-001" in str(exc)
        assert exc.action == "rollback"
        assert exc.incident_id == "INC-001"

    def test_is_domain_exception(self) -> None:
        assert issubclass(ApprovalRequiredError, IncidentCommanderError)


class TestToolExecutionError:
    def test_message_includes_tool_and_reason(self) -> None:
        exc = ToolExecutionError("query_logs", "timeout after 30s")
        assert "query_logs" in str(exc)
        assert "timeout after 30s" in str(exc)


class TestMaxCyclesExceededError:
    def test_message_includes_cycles(self) -> None:
        exc = MaxCyclesExceededError(5)
        assert "5" in str(exc)


class TestRollbackError:
    def test_message_includes_service(self) -> None:
        exc = RollbackError("checkout-api", "deployment not found")
        assert "checkout-api" in str(exc)
        assert exc.service == "checkout-api"
