# Stage 7: Observability, Recovery Drills, and Deterministic Operations

**Version**: v2.6.0 (planned)
**Date**: 2026-02-09
**Status**: All exit gates passed

---

## Overview

Stage 7 closes the gap between "release candidate" and "operationally mature" through five objectives:

1. **End-to-end traceability hardening** -- correlation IDs across gateway, pipeline, adapters, DLQ
2. **Incident bundle export** -- one-command diagnostic packaging for any time window
3. **Chaos + recovery certification** -- fault-injection tests with hard acceptance gates
4. **Backup/restore discipline** -- codified state backup with integrity verification
5. **Release automation v2** -- 12-gate promotion checklist with stricter evidence checks

---

## 1. Correlation ID Traceability

### Problem
WebSocket stream path had 5 gaps where correlation IDs were either missing or substituted with turn_id, breaking the causal chain for request tracing.

### Fix
- Generate per-turn `correlation_id` (`req_xxx`) at `input.text` entry point in stream handler
- Propagate to all downstream calls: `memory_client.search`, `router_client.chat`, `openclaw_client.execute`
- Fixed confirmation approve endpoint to pass correlation_id to openclaw
- Added `correlation_id` field to all `turn_log`, `tool_log`, `error_log` JSONL records

### Coverage
Every action from any entry point (HTTP, WebSocket, DLQ replay) now carries a `correlation_id` through the entire call chain. Clients can supply `X-Correlation-ID` header to link external traces.

### Files Modified
- `routes/stream.py` -- correlation_id generation, propagation, logging
- `main.py` -- confirmation approve correlation_id propagation

---

## 2. Incident Bundle Export

### Script: `scripts/export-incident-bundle.ps1`
```powershell
.\scripts\export-incident-bundle.ps1                    # Last 1 hour
.\scripts\export-incident-bundle.ps1 -WindowMinutes 30  # Last 30 minutes
```

### Bundle Contents
| Directory | Contents |
|-----------|----------|
| `health/` | Service health snapshots, supervisor summary |
| `breakers/` | Circuit breaker states, time-series metrics |
| `dlq/` | Dead letter queue records |
| `actions/` | Recent actions timeline, pending actions |
| `logs/` | JSONL logs filtered by time window |
| `config/` | Dependency manifest, frozen requirements, config |
| `audit/` | Action audit trails |
| `metadata.json` | Bundle metadata (git commit, Python version, errors) |

### API Endpoint
```
GET /v1/diagnostics/snapshot?last_n=50
```
Returns health, breakers, DLQ, and recent actions in a single JSON response.

---

## 3. Chaos + Recovery Certification

### Test Suite: `test_stage7_chaos_recovery.py` (15 tests)

| Test Class | Tests | Gate |
|------------|-------|------|
| TestChaosAdapterTimeout | 2 | Action failure creates DLQ entry with failure class |
| TestChaosBreakerTrip | 3 | Breaker state, metrics, reset |
| TestChaosDLQReplayAfterRecovery | 2 | Dry-run non-destructive, real replay marks as replayed |
| TestChaosCorrelationIDSurvival | 3 | Correlation ID preserved through failure and recovery |
| TestChaosRecoveryTime | 2 | Recovery within 60s RTO budget, health supervisor green |
| TestChaosServiceRestart | 3 | Health, breaker consistency, pipeline functional |

### RTO Budget
- **Target**: 60 seconds for full breaker reset + action execution
- **Actual**: < 1 second (breaker reset is instantaneous)

---

## 4. Backup/Restore Discipline

### API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/backups` | POST | Create full state backup |
| `/v1/backups` | GET | List available backups |
| `/v1/backups/{id}/verify` | GET | SHA-256 integrity verification |
| `/v1/backups/{id}/restore/dlq` | POST | Restore DLQ records (dry_run default) |

### Backup Contents
- Dead letter queue records (full history)
- Action pipeline records
- Circuit breaker state and metrics
- Configuration snapshots (sonia-config, requirements-frozen, dependency-lock)

### Integrity Verification
Each backup includes a `manifest.json` with SHA-256 checksums for every artifact file. The `/verify` endpoint re-computes checksums and reports pass/fail per artifact.

### Test Suite: `test_stage7_backup_restore.py` (10 tests)

| Test Class | Tests |
|------------|-------|
| TestBackupCreate | 4 (manifest, DLQ, actions, breakers) |
| TestBackupVerify | 2 (fresh backup passes, nonexistent fails) |
| TestBackupList | 2 (returns backups, includes metadata) |
| TestDLQRestore | 2 (dry-run validates, nonexistent fails) |

---

## 5. Release Automation v2

### Promotion Gate v2: `scripts/promotion-gate-v2.ps1`

12-gate checklist that must ALL pass before promoting:

| Gate | Check | Blocking? | New? |
|------|-------|-----------|------|
| 1 | Full regression (0 failed) | Yes | |
| 2 | Health supervisor (healthy) | Yes | |
| 3 | Circuit breakers (all closed) | Yes | |
| 4 | Dead letter queue (0 unresolved) | No | |
| 5 | Dependency lock integrity | Yes | |
| 6 | Frozen requirements manifest | Yes | |
| 7 | Chaos suite passes | Yes | NEW |
| 8 | Backup/restore integrity verified | Yes | NEW |
| 9 | Diagnostics snapshot functional | Yes | NEW |
| 10 | Correlation ID in action responses | Yes | NEW |
| 11 | Rollback script exists | Yes | NEW |
| 12 | Incident bundle export script exists | Yes | NEW |

---

## New Files (Stage 7)

| File | Purpose |
|------|---------|
| `services/api-gateway/state_backup.py` | State backup/restore manager |
| `scripts/export-incident-bundle.ps1` | Incident bundle export |
| `scripts/promotion-gate-v2.ps1` | 12-gate promotion checklist |
| `tests/integration/test_stage7_chaos_recovery.py` | 15 chaos + recovery tests |
| `tests/integration/test_stage7_backup_restore.py` | 10 backup/restore tests |
| `docs/STAGE7_OBSERVABILITY.md` | This document |

## Modified Files (Stage 7)

| File | Changes |
|------|---------|
| `services/api-gateway/main.py` | Diagnostics snapshot, backup/restore endpoints, correlation ID fix |
| `services/api-gateway/routes/stream.py` | Correlation ID generation and propagation |

---

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| Stage 2: Turn pipeline | 8 | PASS |
| Stage 3: Voice sessions | 25 | PASS |
| Stage 4: Multimodal | 26 | PASS |
| Stage 5: Action pipeline | 78 | PASS |
| Stage 6: Reliability | 27 | PASS |
| Stage 7: Chaos + recovery | 15 | PASS |
| Stage 7: Backup/restore | 10 | PASS |
| **Total** | **189** | **ALL PASS** |

---

## Exit Gates

| Gate | Criterion | Result |
|------|-----------|--------|
| 1 | 0 unrecoverable failures across chaos suite | PASS (15/15 chaos tests green) |
| 2 | 100% actions include correlation IDs | PASS (all entry points generate + propagate) |
| 3 | Recovery drill meets RTO target (< 60s) | PASS (< 1s actual) |
| 4 | Restore test proves integrity and replay safety | PASS (10/10 backup tests green) |
| 5 | Promotion gate v2 all-pass | PASS (12/12 gates) |
