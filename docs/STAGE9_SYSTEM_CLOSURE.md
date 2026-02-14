# Stage 9: System Closure (v2.9.0)

## Overview

v2.9 closes all P0/P1 gaps identified in the forensic audit and clears
accumulated hygiene debt. The result: every service layer is wired,
tested, and operating with production semantics.

## What Was Closed

### A. Model Router -- Cloud Provider Implementation

**Before:** Anthropic and OpenRouter providers returned `{"status": "not_implemented"}`.
The system was locked to local Ollama models only.

**After:** Both providers are fully implemented:
- **AnthropicProvider**: httpx-based Messages API integration with system message
  extraction, vision routing, and structured error handling.
- **OpenRouterProvider**: OpenAI-compatible chat/completions API with proper
  HTTP-Referer and X-Title headers.
- **ProviderRouter**: Tries providers in priority order (ollama -> anthropic ->
  openrouter) with automatic fallback on failure.
- **Routing policy**: `local_only`, `cloud_allowed` (default), `provider_pinned`.

Tests: 21 integration tests (provider parity, routing policy, health, features).

### B. EVA-OS -- Facade to Real Control Plane

**Before:** `/status` and `/health/all` returned hardcoded data. The
ServiceSupervisor and state machine code existed as dead code.

**After:** EVA-OS performs real HTTP health probes to all downstream services:
- **ServiceSupervisor**: Background polling loop (15s), probes each service's
  `/healthz` endpoint via httpx.
- **State machine**: HEALTHY -> DEGRADED -> UNREACHABLE -> RECOVERING with
  configurable thresholds (1 failure = degraded, 3 = unreachable, 2 consecutive
  successes = recovered).
- **Event emission**: State transitions emit typed EventEnvelope events
  (supervision.service.healthy, degraded, unreachable, recovered).
- **Dependency graph**: Typed service dependencies exposed via
  `/v1/supervision/dependency-graph`.
- **Maintenance mode**: Toggle via `/v1/supervision/maintenance-mode`.

Tests: 19 integration tests (state transitions, event emission, probes).

### C. Memory Engine -- Hybrid Search Pipeline

**Before:** All search was SQL `LIKE %query%` -- substring matching only.
The BM25 index, HNSW vectors, embeddings client, chunker, and retriever
existed as ~1,500 lines of disconnected code.

**After:** HybridSearchLayer wired into main.py:
- **BM25 ranking**: In-memory full-text ranking, pre-loaded from existing
  ledger on startup, incrementally updated on each store.
- **LIKE fallback**: Always runs alongside BM25 to catch what ranking misses.
- **Deduplication**: Results merged from both sources, sorted by score.
- **Token budget**: `/v1/search` accepts `max_tokens` parameter for bounded
  retrieval (approx 4 chars/token).
- **Provenance tracking**: Every stored memory gets provenance recorded in
  `audit_log` with source_type and source_id chain.
- **Provenance endpoints**: `/v1/provenance/{id}` and `/v1/provenance/{id}/chain`.

Tests: 28 integration tests (BM25, hybrid search, provenance, token budget,
endpoint wiring, no-stubs verification).

### D. Hygiene Sweep

| Item | Change |
|------|--------|
| Lifecycle migration | All 6 core services migrated from `@app.on_event` to `@asynccontextmanager` lifespan |
| Version centralization | `services/shared/version.py` (SONIA_VERSION = "2.9.0") imported by all services |
| Dependency dedup | Deleted `config/requirements-frozen.txt` (BOM-corrupted subset) |
| Gitignore | Added `tests/*.txt`, `DumpStack.log.tmp`; changed `state/` to `/state/` (root-only) |

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| v2.9 Model Routing | 21 | All green |
| v2.9 EVA Supervision | 19 | All green |
| v2.9 Memory Hybrid | 28 | All green |
| **v2.9 Total** | **68** | **All green** |

## Promotion Gate

12 gates covering: provider parity, EVA supervision, hybrid search,
version consistency, dependency single-source, lifecycle modernization,
stub removal, supervision wiring, gitignore coverage.

Run: `powershell S:\scripts\promotion-gate-v29.ps1`

## Files Changed

### New Files
- `services/shared/version.py` -- canonical version
- `services/memory-engine/hybrid_search.py` -- BM25 + LIKE hybrid layer
- `services/eva-os/service_supervisor.py` -- real health probing + state machine
- `tests/integration/test_v29_model_routing.py` -- 21 tests
- `tests/integration/test_v29_eva_supervision.py` -- 19 tests
- `tests/integration/test_v29_memory_hybrid.py` -- 28 tests
- `scripts/promotion-gate-v29.ps1` -- 12-gate promotion checklist
- `docs/STAGE9_SYSTEM_CLOSURE.md` -- this document

### Modified Files
- `services/model-router/providers.py` -- Anthropic + OpenRouter implementations
- `services/model-router/main.py` -- routing policy, version, lifespan
- `services/eva-os/main.py` -- real supervision, version, lifespan
- `services/memory-engine/main.py` -- hybrid search + provenance wiring, version, lifespan
- `services/memory-engine/core/provenance.py` -- real DB tracking (was stub)
- `services/api-gateway/main.py` -- version, lifespan
- `services/openclaw/main.py` -- version, lifespan
- `services/pipecat/main.py` -- version, lifespan
- `services/shared/events.py` -- 5 supervisory event types added
- `.gitignore` -- test artifacts, root-only state/

### Deleted Files
- `config/requirements-frozen.txt` -- duplicate with BOM corruption
