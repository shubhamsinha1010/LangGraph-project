"""LangChain @tool-decorated wrappers around the backend interfaces.

Each tool follows the same pattern:
1. Accept a small, flat input (LLMs struggle with nested schemas).
2. Call the injected backend.
3. Return a plain string the LLM can parse.

Backends are injected via module-level singletons from services/backends.py —
this avoids passing them through LangGraph state and keeps tools pure functions.
"""

from langchain_core.tools import tool

from incident_commander.services.backends import get_backends


# --------------------------------------------------------------------------- #
#  Investigation tools (read-only — no approval needed)
# --------------------------------------------------------------------------- #

@tool
def query_logs(service: str, window_minutes: int = 15) -> str:
    """Query recent error logs for a service.

    Args:
        service: The service name to query logs for.
        window_minutes: How far back to look (default 15 minutes).
    """
    backends = get_backends()
    result = backends.logs.query_errors(service, window_minutes)
    lines = [
        f"Service: {result.service}",
        f"Window: {result.time_window_minutes}m",
        f"Error count: {result.error_count}",
        f"Error rate: {result.error_rate_pct}%",
        "Top errors:",
        *[f"  - {e}" for e in result.top_errors],
        "Sample traces:",
        *[f"  - {t}" for t in result.sample_traces],
    ]
    return "\n".join(lines)


@tool
def query_metrics(service: str, window_minutes: int = 15) -> str:
    """Query performance metrics for a service.

    Args:
        service: The service name to query.
        window_minutes: Metrics window in minutes (default 15).
    """
    backends = get_backends()
    r = backends.metrics.query_service(service, window_minutes)
    lines = [
        f"Service: {r.service}",
        f"p99 latency: {r.p99_latency_ms}ms (baseline: {r.baseline_comparison.get('p99_latency_baseline_ms')}ms)",
        f"Error rate: {r.error_rate_pct}% (baseline: {r.baseline_comparison.get('error_rate_baseline_pct')}%)",
        f"Request rate: {r.request_rate_rps} rps",
        f"CPU: {r.cpu_utilization_pct}%  Memory: {r.memory_utilization_pct}%",
        "Anomalies:" if r.anomalies else "Anomalies: none",
        *[f"  ! {a}" for a in r.anomalies],
    ]
    return "\n".join(lines)


@tool
def query_recent_changes(service: str, lookback_hours: int = 24) -> str:
    """Query recent deploys, config changes, and feature flags for a service.

    Args:
        service: The service name to inspect.
        lookback_hours: How many hours to look back (default 24).
    """
    backends = get_backends()
    r = backends.changes.query_recent(service, lookback_hours)
    if not r.recent_changes:
        return f"No changes found for {service} in the last {lookback_hours}h."
    lines = [f"Recent changes for {service}:"]
    for c in r.recent_changes:
        lines.append(
            f"  [{c.change_type.upper()}] {c.change_id} by {c.author} "
            f"at {c.timestamp} — {c.description} (risk: {c.risk_level})"
        )
        lines.append(f"    diff: {c.diff_summary}")
    if r.last_deploy_minutes_ago is not None:
        lines.append(f"Last deploy: {r.last_deploy_minutes_ago} minutes ago")
    return "\n".join(lines)


@tool
def search_runbooks(alert_description: str, top_k: int = 3) -> str:
    """Search the runbook library for known remediation steps.

    Args:
        alert_description: A short natural-language description of the alert.
        top_k: Number of runbooks to return (default 3).
    """
    backends = get_backends()
    r = backends.runbooks.search(alert_description, top_k)
    if not r.matches:
        return "No runbooks matched the given alert description."
    lines = [f"Runbooks for: '{r.alert_pattern}'"]
    for m in r.matches:
        lines.append(f"\n[{m.runbook_id}] {m.title} (relevance: {m.relevance_score:.0%})")
        lines.append(f"  Typical resolution: ~{m.typical_resolution_minutes} minutes")
        lines.append("  Steps:")
        for i, step in enumerate(m.steps, 1):
            lines.append(f"    {i}. {step}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Destructive tools (require HITL approval before the executor calls them)
# --------------------------------------------------------------------------- #

@tool
def rollback_to_previous_version(service: str, task_id: str) -> str:
    """Roll back a service to its immediately previous deployed version.

    IMPORTANT: This tool must only be called by the Executor node after
    explicit human approval has been recorded in the graph state.

    Args:
        service: The service to roll back.
        task_id: Idempotency key — re-running with the same task_id is safe.
    """
    backends = get_backends()
    r = backends.rollback.rollback_to_previous(service, task_id)
    if r.success:
        return (
            f"ROLLBACK SUCCESS: {r.message}\n"
            f"Verification: health={r.verification.get('health_check')}, "
            f"error_rate={r.verification.get('error_rate_after_pct')}%, "
            f"p99={r.verification.get('p99_latency_after_ms')}ms"
        )
    return f"ROLLBACK FAILED: {r.message}"


@tool
def rollback_to_version(service: str, version: str, task_id: str) -> str:
    """Roll back a service to a specific named version.

    IMPORTANT: This tool must only be called by the Executor node after
    explicit human approval has been recorded in the graph state.

    Args:
        service: The service to roll back.
        version: The target version string (e.g. 'v2.3.1').
        task_id: Idempotency key.
    """
    backends = get_backends()
    r = backends.rollback.rollback_to_version(service, version, task_id)
    if r.success:
        return (
            f"ROLLBACK SUCCESS: {r.message}\n"
            f"Verification: health={r.verification.get('health_check')}, "
            f"error_rate={r.verification.get('error_rate_after_pct')}%, "
            f"p99={r.verification.get('p99_latency_after_ms')}ms"
        )
    return f"ROLLBACK FAILED: {r.message}"


# Convenience groupings used when binding tools to agents
INVESTIGATION_TOOLS = [query_logs, query_metrics, query_recent_changes, search_runbooks]
DESTRUCTIVE_TOOLS = [rollback_to_previous_version, rollback_to_version]
ALL_TOOLS = INVESTIGATION_TOOLS + DESTRUCTIVE_TOOLS
