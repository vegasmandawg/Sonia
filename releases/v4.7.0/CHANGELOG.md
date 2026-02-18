# SONIA v4.7.0-rc1 Changelog

## Trustable Operations + Deterministic Control

### Epic A: Audit-Chain Integrity (6/6 gates at baseline)
- Hash-chained audit log, tamper detection, signed bundles
- Replay provenance, cross-service trace, audit export

### Epic B: Control-Plane Determinism (6/6 gates)
- Idempotent approve/deny with deterministic conflict envelopes
- Durable idempotency store (SQLite WAL, TTL-expiring)
- Session isolation under concurrent load
- Restart budget persistence (fail-closed on corruption)
- 36 new tests across 6 test files

### Epic C: Runtime SLO Automation (6/6 gates)
- SLOGuardrails 3-state machine (NORMAL/DEGRADED/RECOVERING)
- Recovery exit criteria with consecutive healthy windows
- /v1/slo/status + /v3/slo/status diagnostics endpoints

### Gate Summary
- 84/84 PROMOTE (66 floor + 18 delta, schema 14.0)
- 51 offline tests green (36 new Epic B + 15 existing)
