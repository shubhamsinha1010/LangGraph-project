# Incident Commander

> A production-grade SRE multi-agent copilot built on **LangGraph 1.0**.  
> Demonstrates every concept that appears in LangGraph interviews and production deployments.

---

## What it does

When a production alert fires, Incident Commander:

1. **Investigates in parallel** — four specialist agents (log, metrics, change, runbook) run concurrently as LangGraph subgraph fan-out.
2. **Plans** — a Planner agent synthesises findings into a diagnosis, confidence score, and ranked action list.
3. **Pauses for humans** — if the top action is destructive (rollback, restart), the graph interrupts and waits indefinitely at the `human_approval` node.
4. **Resumes** — after the engineer approves via `PATCH /api/v1/incidents/{id}/approve`, the graph reads its checkpoint and continues from exactly where it stopped.
5. **Executes and resolves** — the Executor calls the rollback tool, verifies recovery, and marks the incident resolved.

---

## LangGraph concepts demonstrated

| Concept | Where |
|---|---|
| `StateGraph` + `TypedDict` state | `incident_commander/core/state.py` |
| Custom reducers (parallel-safe fan-out) | `_merge_findings` in `state.py` |
| Subgraph (investigation fan-out) | `graphs/investigation_subgraph.py` |
| `interrupt_before` HITL pause | `graphs/supervisor.py` |
| `update_state` + resume | `api/routes/incidents.py` (approve endpoint) |
| Conditional routing / edges | `agents/supervisor.py` |
| MemorySaver (dev) / PostgresSaver (prod) | `services/checkpointer.py` |
| `thread_id` scoped checkpointing | Every `graph.invoke` call |
| Tool binding + tool-use loop | Every analyst node |
| SSE streaming | `api/routes/incidents.py` |
| Audit trail via `operator.add` reducer | `core/state.py` |
| Supervisor + worker multi-agent pattern | `graphs/supervisor.py` |

---

## Project structure

```
incident-commander/
├── incident_commander/
│   ├── core/
│   │   ├── config.py          # pydantic-settings singleton
│   │   ├── constants.py       # enums + node name constants
│   │   ├── exceptions.py      # typed domain exceptions
│   │   ├── logging.py         # structlog configuration
│   │   └── state.py           # IncidentStateDict + reducers
│   ├── agents/
│   │   ├── base.py            # shared prompt loading + JSON parsing
│   │   ├── log_analyst.py
│   │   ├── metrics_analyst.py
│   │   ├── change_analyst.py
│   │   ├── runbook_retriever.py
│   │   ├── planner.py
│   │   ├── executor.py
│   │   ├── supervisor.py      # routing functions + supervisor node
│   │   └── resolver.py
│   ├── graphs/
│   │   ├── investigation_subgraph.py   # parallel fan-out subgraph
│   │   └── supervisor.py              # top-level graph + HITL compile
│   ├── tools/
│   │   ├── base.py                    # ABCs for all backends
│   │   ├── fake_adapters.py           # deterministic in-memory adapters
│   │   └── langchain_tools.py         # @tool wrappers + tool groups
│   ├── services/
│   │   ├── backends.py        # service locator — swap real for fake here
│   │   ├── checkpointer.py    # MemorySaver / AsyncPostgresSaver factory
│   │   └── llm_factory.py     # provider-agnostic LLM construction
│   └── prompts/               # markdown system prompts per agent
├── api/
│   ├── app.py                 # FastAPI factory + lifespan
│   ├── middleware/logging.py  # structured request logging
│   ├── routes/
│   │   ├── health.py
│   │   └── incidents.py       # CRUD + approve + SSE stream
│   └── schemas/incident.py    # Pydantic request/response models
├── tests/
│   ├── fixtures/              # shared pytest fixtures
│   ├── unit/
│   │   ├── agents/            # supervisor, planner, executor (mocked LLM)
│   │   └── tools/             # fake adapter unit tests
│   └── integration/           # full graph routing + HITL tests
├── docker/Dockerfile
├── docker-compose.yml
├── langgraph.json             # LangGraph Cloud manifest
├── pyproject.toml
└── Makefile
```

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/shubhamsinha1010/LangGraph-project.git
cd LangGraph-project
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Set OPENAI_API_KEY in .env

# 3. Run the API
make dev
# or: python main.py

# 4. Open the docs
open http://localhost:8000/docs
```

### Trigger an incident (curl)

```bash
# Start an incident — returns SSE stream
curl -N -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "checkout-api: high error rate (18%)",
    "description": "checkout-api p99 latency spiked to 2.4s. Error rate is 18%. Payments are failing.",
    "severity": "critical",
    "affected_service": "checkout-api",
    "alert_source": "datadog"
  }'

# The stream will pause when awaiting approval.
# Grab the incident_id from the SSE events, then approve:
INCIDENT_ID=<paste-id-here>

curl -X PATCH http://localhost:8000/api/v1/incidents/$INCIDENT_ID/approve \
  -H "Content-Type: application/json" \
  -d '{"action_index": 0, "notes": "Looks good, proceed with rollback."}'
```

---

## Run tests

```bash
make test          # all tests
make test-unit     # unit tests only (no LLM calls, instant)
make test-integration  # integration tests
```

---

## Production deployment

```bash
# With Postgres checkpointing
make docker-up
```

Set `CHECKPOINT_BACKEND=postgres` and `DATABASE_URL` in your environment.  
The `AsyncPostgresSaver` is automatically used — conversations survive restarts.

---

## Design principles

- **SOLID** — each class/module has one reason to change; backends depend on ABCs not concretions.
- **DRY** — prompt loading, JSON parsing, and tool-use loops are in `agents/base.py`, not repeated per agent.
- **Dependency Inversion** — all five backends (`logs`, `metrics`, `changes`, `runbooks`, `rollback`) are injected via `services/backends.py`. Swap to real Datadog/K8s without touching agent code.
- **Open/Closed** — add a new specialist agent by adding a node + prompt; no existing code changes.
- **Idempotency** — every destructive tool call accepts a `task_id` so replays are safe.

---

## Extending to real infrastructure

| Component | How to swap |
|---|---|
| Logs | Implement `LogBackend` ABC, point at Datadog/CloudWatch |
| Metrics | Implement `MetricsBackend` ABC, point at Prometheus/Datadog |
| Changes | Implement `ChangeBackend` ABC, point at GitHub Deployments/ArgoCD |
| Rollback | Implement `RollbackBackend` ABC, call `kubectl rollout undo` |
| Runbooks | Implement `RunbookBackend` ABC, search Confluence/Notion |

Change only `services/backends.py` — every agent automatically uses the new implementation.
