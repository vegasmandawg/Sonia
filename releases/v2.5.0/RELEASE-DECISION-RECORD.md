# Release Decision Record: v2.5.0

**Decision**: PROMOTE v2.5.0-rc1 to v2.5.0 GA
**Date**: 2026-02-09
**Commit**: ac64fbbb09791b0f5ee0f8c6249abc2a8942d476
**Code Changes Since RC**: None (zero-diff promotion)

---

## Evidence Summary

| Gate | Result | Detail |
|------|--------|--------|
| RC artifact integrity | PASS | Tag v2.5.0-rc1 resolves to ac64fbbb, working tree clean |
| Dependency lock match | PASS | pip freeze matches requirements-frozen.txt (45 packages, 0 drift) |
| Clean-room rebuild | PASS | Fresh venv from frozen deps produces identical package set |
| Clean-room regression | PASS | 164/164 tests pass from rebuilt environment (46.62s) |
| Soak test | PASS | 240 actions, 0 SLO violations, 20 expected transient errors |
| Ops drill: DLQ scenario | PASS | Dead letter created, counted, retrievable |
| Ops drill: DLQ dry-run replay | PASS | Validated without side effects, state preserved |
| Ops drill: breaker metrics | PASS | Success events tracked, bounded buffer functioning |
| Ops drill: rollback dry-run | PASS | Full simulation completed, all files identified |
| Promotion gate | PASS | All 6 gates passed |

## Scope (Stages 2-6)

- **Stage 2**: Turn pipeline (memory recall, model chat, tool exec, memory write)
- **Stage 3**: Voice session runtime, WebSocket stream, tool safety gate, confirmation queue
- **Stage 4**: Vision ingestion, turn quality controls, memory policy, latency instrumentation
- **Stage 5**: Action pipeline (13 capabilities), desktop adapters, circuit breaker, DLQ, audit trail
- **Stage 6**: Retry taxonomy, DLQ replay dry-run, breaker metrics, SLO budgets, release discipline

## Known Limitations

- Clipboard operations under concurrency produce transient EXECUTION_FAILED errors (Windows clipboard lock contention). Non-blocking; actions succeed on retry.
- Breaker metric buffer bounded at 200 events. Older events rotate out. Sufficient for operational monitoring.
- EVA-OS remains a skeleton with hardcoded health data.

## Rollback Plan

1. `S:\scripts\rollback-to-stage5.ps1 -DryRun` to preview changes
2. `S:\scripts\rollback-to-stage5.ps1` to execute rollback
3. `git checkout v2.5.0-stage5` to restore codebase to Stage 5 state

Rollback verified via dry-run during ops drill.
