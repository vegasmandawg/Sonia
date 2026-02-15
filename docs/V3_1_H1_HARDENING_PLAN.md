# v3.1 H1 Hardening Plan

**Status:** Active
**Branch:** `v3.1-dev`
**Contract baseline:** v3.0.0 (no behavior-contract drift unless explicitly approved)
**Objective:** Reliability hardening only — zero new features

---

## Scope Lock

H1 freezes v3.1 to reliability work exclusively:

1. No new API endpoints or schema changes
2. No new event types or message formats
3. SONIA_CONTRACT stays at `v3.0.0`
4. All v3.0 M1-M4 regression tests must remain green throughout

---

## Owners

| Area                          | Owner           |
|-------------------------------|-----------------|
| Replay determinism            | memory-engine   |
| Crash recovery integrity      | api-gateway     |
| Incident bundle roundtrip     | ops / scripts   |
| Concurrency race guards       | api-gateway     |
| Dependency / provenance strict| shared + memory |

---

## Metrics and Pass/Fail Thresholds

### 1. Deterministic Replay Equivalence

**What:** Given the same sequence of `EventEnvelope` inputs, the turn pipeline produces byte-identical memory writes and provenance records.

**Metric:** Replay divergence count
**Threshold:** 0 divergences across 50-event replay
**How to test:** Capture a golden event sequence, replay it, diff memory state.

### 2. Crash-Recovery Integrity

**What:** After a simulated crash (kill api-gateway mid-turn), restarting produces a consistent state with no orphaned sessions, no phantom confirmations, and provenance chain intact.

**Metric:** Orphaned artifact count post-recovery
**Threshold:** 0 orphaned sessions, 0 phantom confirmations, 0 broken provenance chains
**How to test:** Create sessions + confirmations, simulate crash, restart, audit state.

### 3. Incident Bundle Roundtrip Fidelity

**What:** `export-incident-bundle.ps1` output contains all expected sections and the bundle can be parsed back to reconstruct the incident timeline.

**Metric:** Missing section count
**Threshold:** 0 missing sections, all timestamps parseable
**How to test:** Trigger bundle export, parse JSON/text output, validate schema.

### 4. Concurrency Race Guard

**What:** Under concurrent WebSocket connections performing session create/touch/close and confirmation approve/deny, no data corruption occurs.

**Metric:** Race condition errors, state corruption events
**Threshold:** 0 corruptions across 20 concurrent actors, 100 operations each
**How to test:** asyncio.gather with parallel session + confirmation operations.

### 5. Dependency and Provenance Strictness

**What:** All provenance records have non-empty required fields (memory_id, source_type, tracked_at). Dependency snapshot matches frozen requirements.

**Metric:** Invalid provenance records; dependency drift count
**Threshold:** 0 invalid records; 0 undeclared dependencies
**How to test:** Enumerate provenance records, validate schema. Compare pip freeze to frozen deps.

---

## Deliverables

| #  | Deliverable                                        | Path                                              |
|----|----------------------------------------------------|----------------------------------------------------|
| D1 | This plan                                          | `docs/V3_1_H1_HARDENING_PLAN.md`                  |
| D2 | Gate specification                                 | `docs/V3_1_GATE_SPEC.md`                           |
| D3 | Replay determinism tests                           | `tests/hardening/test_replay_determinism.py`       |
| D4 | Recovery integrity tests                           | `tests/hardening/test_recovery_integrity.py`       |
| D5 | Confirmation non-bypass under load tests           | `tests/hardening/test_confirmation_non_bypass_under_load.py` |
| D6 | Gate-v31 expansion (5 new gates)                   | `scripts/release/gate-v31.py`                      |
| D7 | Chaos fault injection scripts                      | `scripts/chaos/*.py`                               |
| D8 | Evidence archive                                   | `reports/hardening-v31/`                           |

---

## Commit Cadence

1. `docs(v3.1): add H1 hardening plan and success metrics`
2. `test(v3.1): add hardening test suites`
3. `gate(v3.1): expand gate-v31 with 5 hardening gates`
4. `chaos(v3.1): add fault injection scripts`

---

## Definition of Done

- [ ] All gate-v31 checks PASS (original 12 + 5 new hardening gates = 17)
- [ ] Full v3.0 M1-M4 regression green (112 tests)
- [ ] No contract drift (SONIA_CONTRACT == v3.0.0)
- [ ] Soak + chaos evidence archived to `reports/hardening-v31/`
- [ ] No new API surface or schema changes
