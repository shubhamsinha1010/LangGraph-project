"""Unit tests for Pydantic output models — validation and field constraints."""

import pytest
from pydantic import ValidationError

from incident_commander.core.output_models import (
    ChangeAnalystOutput,
    ExecutorOutput,
    LogAnalystOutput,
    MetricsAnalystOutput,
    PlannerOutput,
    ProposedAction,
    RunbookRetrieverOutput,
)


class TestLogAnalystOutput:
    def test_valid_output(self) -> None:
        out = LogAnalystOutput(findings=["error rate 18%"], error_count=200, error_rate_pct=18.0)
        assert out.error_count == 200
        assert len(out.findings) == 1

    def test_defaults_are_populated(self) -> None:
        out = LogAnalystOutput(findings=[])
        assert out.error_count == 0
        assert out.relevant_traces == []


class TestMetricsAnalystOutput:
    def test_valid_cause_category(self) -> None:
        out = MetricsAnalystOutput(findings=[], likely_cause_category="code_regression")
        assert out.likely_cause_category == "code_regression"

    def test_invalid_cause_category_raises(self) -> None:
        with pytest.raises(ValidationError):
            MetricsAnalystOutput(findings=[], likely_cause_category="aliens")  # type: ignore


class TestProposedAction:
    def test_valid_action_types(self) -> None:
        for atype in ("rollback", "restart", "scale", "config_change", "investigate_more", "escalate"):
            a = ProposedAction(
                action_type=atype,  # type: ignore[arg-type]
                description="do it",
                service="api",
                is_destructive=False,
                priority=1,
            )
            assert a.action_type == atype

    def test_invalid_action_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProposedAction(
                action_type="nuke",  # type: ignore
                description="x",
                service="api",
                is_destructive=True,
                priority=1,
            )

    def test_priority_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProposedAction(
                action_type="rollback",
                description="x",
                service="api",
                is_destructive=True,
                priority=99,
            )


class TestPlannerOutput:
    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            PlannerOutput(diagnosis="x", confidence=1.5, proposed_actions=[])

    def test_valid_planner_output(self) -> None:
        out = PlannerOutput(
            diagnosis="Deploy caused the issue.",
            confidence=0.85,
            proposed_actions=[
                ProposedAction(
                    action_type="rollback",
                    description="Rollback",
                    service="api",
                    is_destructive=True,
                    priority=1,
                )
            ],
        )
        assert out.confidence == 0.85
        assert len(out.proposed_actions) == 1


class TestExecutorOutput:
    def test_valid_next_step(self) -> None:
        out = ExecutorOutput(
            action_taken="done",
            tool_called="rollback",
            success=True,
            result_summary="ok",
            next_step="resolve",
        )
        assert out.next_step == "resolve"

    def test_invalid_next_step_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExecutorOutput(
                action_taken="done",
                tool_called="rollback",
                success=True,
                result_summary="ok",
                next_step="party",  # type: ignore
            )
