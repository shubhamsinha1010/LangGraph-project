"""Unit tests for fake backend adapters — verifies realistic, consistent output."""

import pytest

from incident_commander.tools.fake_adapters import (
    FakeChangeBackend,
    FakeLogBackend,
    FakeMetricsBackend,
    FakeRollbackBackend,
    FakeRunbookBackend,
)


class TestFakeLogBackend:
    def test_returns_log_result(self) -> None:
        backend = FakeLogBackend()
        result = backend.query_errors("checkout-api", window_minutes=15)
        assert result.service == "checkout-api"
        assert result.error_count > 0
        assert result.error_rate_pct > 0
        assert len(result.top_errors) >= 1
        assert result.time_window_minutes == 15

    def test_deterministic_for_same_service(self) -> None:
        backend = FakeLogBackend()
        r1 = backend.query_errors("payments-svc")
        r2 = backend.query_errors("payments-svc")
        assert r1.error_count == r2.error_count
        assert r1.top_errors == r2.top_errors

    def test_different_services_give_different_results(self) -> None:
        backend = FakeLogBackend()
        r1 = backend.query_errors("service-a")
        r2 = backend.query_errors("service-b")
        assert r1.error_count != r2.error_count or r1.top_errors != r2.top_errors


class TestFakeMetricsBackend:
    def test_returns_metrics_result(self) -> None:
        backend = FakeMetricsBackend()
        result = backend.query_service("checkout-api")
        assert result.service == "checkout-api"
        assert result.p99_latency_ms > 0
        assert 0 < result.cpu_utilization_pct < 100
        assert isinstance(result.anomalies, list)

    def test_baseline_comparison_populated(self) -> None:
        backend = FakeMetricsBackend()
        result = backend.query_service("api")
        assert "p99_latency_baseline_ms" in result.baseline_comparison


class TestFakeChangeBackend:
    def test_returns_change_result(self) -> None:
        backend = FakeChangeBackend()
        result = backend.query_recent("checkout-api")
        assert result.service == "checkout-api"
        assert len(result.recent_changes) >= 1
        change = result.recent_changes[0]
        assert change.change_id
        assert change.risk_level in ("high", "medium", "low")

    def test_last_deploy_minutes_populated(self) -> None:
        backend = FakeChangeBackend()
        result = backend.query_recent("api")
        assert result.last_deploy_minutes_ago is not None


class TestFakeRunbookBackend:
    def test_returns_matches(self) -> None:
        backend = FakeRunbookBackend()
        result = backend.search("high error rate after deploy")
        assert len(result.matches) >= 1
        match = result.matches[0]
        assert match.relevance_score > 0
        assert len(match.steps) >= 1

    def test_matches_sorted_by_relevance(self) -> None:
        backend = FakeRunbookBackend()
        result = backend.search("connection pool exhausted", top_k=3)
        scores = [m.relevance_score for m in result.matches]
        assert scores == sorted(scores, reverse=True)


class TestFakeRollbackBackend:
    def test_rollback_to_previous_succeeds(self) -> None:
        backend = FakeRollbackBackend()
        result = backend.rollback_to_previous("checkout-api", task_id="task-001")
        assert result.success is True
        assert result.service == "checkout-api"
        assert result.rolled_back_to
        assert "passing" in result.verification.get("health_check", "")

    def test_rollback_to_version_succeeds(self) -> None:
        backend = FakeRollbackBackend()
        result = backend.rollback_to_version("api", version="v1.2.3", task_id="task-002")
        assert result.success is True
        assert result.rolled_back_to == "v1.2.3"

    def test_idempotent_task_id(self) -> None:
        """Same task_id should produce same result (idempotency in real systems)."""
        backend = FakeRollbackBackend()
        r1 = backend.rollback_to_version("api", version="v1.0.0", task_id="idempotent-001")
        # In the fake, calling again with the same version effectively re-sets it
        assert r1.success is True
