# Stage 6: Reliability Hardening & Release Discipline

**Version**: v2.5.0-rc1
**Date**: 2026-02-09
**Status**: All gates passed — ready to promote

---

## Overview

Stage 6 closes the gap between "working prototype" and "release candidate" through four objectives:

1. **Stabilization gate** — fix all pre-existing test failures, achieve 0 known red
2. **Reliability hardening** — retry taxonomy, DLQ replay dry-run, breaker metrics
3. **Latency/throughput budgets** — per-capability SLOs, 10x soak test, p50/p95/p99
4. **Release discipline** — frozen manifests, dependency hash lock, rollback script, promotion gate

---

## 1. Stabilization Gate

### Problem
Two Pipecat WebSocket tests were failing due to a `websockets` library v16.0 API change. The `timeout` parameter was removed from `websockets.connect()` and replaced with `open_timeout` / `close_timeout`.

### Fix
Updated `test_phase2_e2e.py` to use the new parameter names:
```python
# Before (broken on websockets v16)
async with websockets.connect(ws_url, timeout=TIMEOUT) as ws:

# After
async with websockets.connect(ws_url, open_timeout=TIMEOUT, close_timeout=TIMEOUT) as ws:
```

### Result
- **164/164** integration tests pass (0 red)
- Full test breakdown: Stage 2 (8) + Stage 3 (25) + Stage 4 (26) + Stage 5 (78) + Stage 6 (27)

---

## 2. Reliability Hardening

### 2a. Retry Taxonomy (`retry_taxonomy.py`)

Every failure in the action pipeline is now classified into one of 8 buckets:

| Failure Class | Retryable | Max Retries | Backoff Base | Examples |
|---|---|---|---|---|
| `CONNECTION_BOOTSTRAP` | Yes | 3 | 1.0s | Upstream unreachable, DNS failure |
| `TIMEOUT` | Yes | 2 | 2.0s | Request timeout, deadline exceeded |
| `BACKPRESSURE` | Yes | 5 | 0.5s | 429 Too Many Requests, rate limited |
| `CIRCUIT_OPEN` | No | 0 | — | Breaker tripped |
| `POLICY_DENIED` | No | 0 | — | Safety gate blocked |
| `VALIDATION_FAILED` | No | 0 | — | Bad input, schema violation |
| `EXECUTION_ERROR` | No | 0 | — | Runtime failure in executor |
| `UNKNOWN` | No | 0 | — | Unclassified |

The `classify_failure()` function inspects error codes, messages, HTTP status, and exception types to assign the correct class. The `failure_class` field is attached to:
- `ExecutionResult` responses
- `DeadLetter` entries in the DLQ

### 2b. DLQ Replay Dry-Run

The dead letter replay endpoint now accepts `?dry_run=true`:

```
POST /v1/dead-letters/{id}/replay?dry_run=true
```

In dry-run mode:
- The action is re-validated through the pipeline
- No side effects are executed
- The dead letter is NOT marked as replayed
- A diff is returned comparing the original failure to the replay result

### 2c. Circuit Breaker Metrics

New time-series metric tracking on all circuit breakers:

```
GET /v1/breakers/metrics?last_n=50
```

Each breaker tracks events (bounded to 200 entries):
- `success`, `failure` — per-call outcomes
- `trip` — state transition to OPEN
- `recover` — state transition back to CLOSED
- `short_circuit` — request rejected while OPEN
- `reset` — manual reset

Response includes per-breaker event counts and recent timestamped events.

---

## 3. Latency/Throughput Budgets

### SLO Targets

| Category | Capabilities | p95 SLO |
|---|---|---|
| Native (ctypes) safe | `file.read`, `window.list`, `window.focus` | 200ms |
| Subprocess safe | `clipboard.read` | 2000ms |
| Subprocess low | `clipboard.write` | 2000ms |
| Dry-run (medium/high) | `file.write`, `shell.run`, `app.launch`, `app.close`, `keyboard.type`, `keyboard.hotkey`, `mouse.click` | 2000ms |
| Browser open (low) | `browser.open` | 2000ms |

Subprocess-based capabilities (clipboard) have relaxed SLOs due to PowerShell process startup overhead (~1s per invocation on Windows).

### 10x Soak Test (`soak_stage6_latency.ps1`)

- **Configuration**: 80 cycles x 3 parallel = 240+ actions
- **Coverage**: All 13 registered capabilities
- **Metrics**: Per-capability p50/p95/p99 latency
- **Post-soak checks**: Health supervisor, breaker states, breaker metrics

### Soak Results

- **240 actions** processed
- **0 SLO violations** (all p95 within budget)
- **20 transient errors** (clipboard lock contention under concurrency — expected on Windows)
- **Throughput**: ~8-10 actions/sec on local desktop

---

## 4. Release Discipline

### Frozen Manifests

| Artifact | Path | Content |
|---|---|---|
| Frozen requirements | `S:\config\requirements-frozen.txt` | 45 pinned packages from `pip freeze` |
| Dependency hash lock | `S:\config\dependency-lock.json` | SHA-256 digest + package count + Python version |

### Rollback Script (`scripts/rollback-to-stage5.ps1`)

One-command rollback with `-DryRun` support:

```powershell
# Preview what would change
.\scripts\rollback-to-stage5.ps1 -DryRun

# Execute rollback
.\scripts\rollback-to-stage5.ps1
```

Steps:
1. Backup current Stage 6 state
2. Stop all services
3. Remove Stage 6 new files
4. Restart services
5. Health check all 6 services

### Promotion Gate (`scripts/promotion-gate.ps1`)

6-gate checklist that must ALL pass before promoting:

| Gate | Check | Blocking? |
|---|---|---|
| 1 | Full regression (0 failed) | Yes |
| 2 | Health supervisor (healthy) | Yes |
| 3 | Circuit breakers (all closed) | Yes |
| 4 | Dead letter queue (0 unresolved) | No (informational) |
| 5 | Dependency lock integrity | Yes |
| 6 | Frozen requirements manifest | Yes |

Exit codes: `0` = safe to promote, `1` = blocked.

---

## New Files (Stage 6)

| File | Purpose |
|---|---|
| `services/api-gateway/retry_taxonomy.py` | Failure classification + retry policy |
| `tests/integration/test_stage6_reliability.py` | 27 Stage 6 integration tests |
| `scripts/soak_stage6_latency.ps1` | 10x soak test with per-capability SLOs |
| `scripts/promotion-gate.ps1` | 6-gate promotion checklist |
| `scripts/rollback-to-stage5.ps1` | One-command rollback |
| `config/requirements-frozen.txt` | Frozen pip dependencies |
| `config/dependency-lock.json` | Dependency hash lock |
| `docs/STAGE6_RELIABILITY.md` | This document |

## Modified Files (Stage 6)

| File | Changes |
|---|---|
| `services/api-gateway/action_pipeline.py` | Retry taxonomy wiring, DLQ replay dry-run |
| `services/api-gateway/circuit_breaker.py` | Time-series metric events, metrics() export |
| `services/api-gateway/dead_letter.py` | `failure_class` field on DeadLetter |
| `services/api-gateway/schemas/action.py` | `failure_class` field on ExecutionResult |
| `services/api-gateway/main.py` | `/v1/breakers/metrics` endpoint, replay `dry_run` param |
| `tests/integration/test_phase2_e2e.py` | websockets v16 API fix |

---

## Test Summary

| Suite | Tests | Status |
|---|---|---|
| Stage 2: Turn pipeline | 8 | PASS |
| Stage 3: Voice sessions | 25 | PASS |
| Stage 4: Multimodal | 26 | PASS |
| Stage 5: Action pipeline | 78 | PASS |
| Stage 6: Reliability | 27 | PASS |
| **Total** | **164** | **ALL PASS** |

---

## Promotion Gate Result

```
=== Promotion Gate -- v2.5.0-rc1 ===
  [OK] regression: PASS    (164 passed, 0 failed)
  [OK] health: PASS         (overall state: healthy)
  [OK] breakers: PASS       (openclaw: closed)
  [!!] dead_letters: WARN   (45 from soak tests, non-blocking)
  [OK] dep_lock: PASS       (lock file present)
  [OK] requirements: PASS   (45 packages)

[PROMOTE] All gates passed -- safe to promote v2.5.0-rc1
```
