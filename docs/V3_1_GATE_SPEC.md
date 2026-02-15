# v3.1 Gate Specification

**Gate script:** `scripts/release/gate-v31.py`
**Total gates:** 17 (12 baseline from v3.0 + 5 hardening)
**Report output:** `reports/gate-v31/gate-report.json`

---

## Baseline Gates (1-12, inherited from v3.0)

| # | Gate                        | What it checks                                                  | Pass criteria              |
|---|-----------------------------|-----------------------------------------------------------------|----------------------------|
| 1 | repo_hygiene                | No unexpected untracked/modified files                          | 0 dirty (excluding allowed)|
| 2 | dependency_snapshot         | pip freeze succeeds and writes snapshot                         | exit 0, file written       |
| 3 | version_consistency         | SONIA_VERSION, branch name, M4 doc present                     | all checks pass            |
| 4 | tests_m1                    | M1 contract test suite                                         | 18 passed                  |
| 5 | tests_m2                    | M2 identity test suite                                         | 28 passed                  |
| 6 | tests_m3                    | M3 memory ledger test suite                                    | 38 passed                  |
| 7 | tests_m4                    | M4 perception bridge test suite                                | 28 passed                  |
| 8 | regression_full             | All M1-M4 combined                                             | 112 passed, 0 failed       |
| 9 | perception_invariants       | Perception->typed-memory and provenance chain tests             | all matched tests pass     |
|10 | confirmation_nonbypass      | PerceptionActionGate bypass detection and state machine         | all matched tests pass     |
|11 | manifest_integrity          | SHA-256 hash of key source files, no MISSING files              | 0 missing                  |
|12 | cleanroom_smoke             | Core module imports succeed in fresh Python                     | CLEAN_ROOM_OK              |

---

## Hardening Gates (13-17, new in v3.1)

### Gate 13: `hardening_replay_determinism`

**Purpose:** Verify that replaying a captured event sequence produces identical memory writes.

**Implementation:**
- Runs `tests/hardening/test_replay_determinism.py` via pytest
- Tests capture a golden event sequence, replay it, compare outputs
- Any divergence = FAIL

**Threshold:** 0 divergences, all tests pass

---

### Gate 14: `hardening_recovery_integrity`

**Purpose:** After simulated crash, state is consistent with no orphans.

**Implementation:**
- Runs `tests/hardening/test_recovery_integrity.py` via pytest
- Tests simulate mid-operation crash, verify clean recovery
- Checks: no orphaned sessions, no phantom confirmations, provenance intact

**Threshold:** 0 orphaned artifacts, all tests pass

---

### Gate 15: `hardening_confirmation_load`

**Purpose:** PerceptionActionGate holds invariants under concurrent load.

**Implementation:**
- Runs `tests/hardening/test_confirmation_non_bypass_under_load.py` via pytest
- Tests use asyncio concurrency to stress the gate with parallel approve/deny/expire
- Verifies: no bypass, correct state transitions, counter accuracy

**Threshold:** 0 bypasses, 0 state corruptions, all tests pass

---

### Gate 16: `hardening_chaos_faults`

**Purpose:** Chaos fault injection scripts complete without crashes.

**Implementation:**
- Runs each `scripts/chaos/*.py` script
- Each script simulates a fault class and verifies graceful handling
- Output written to `reports/chaos-v31/`

**Threshold:** All chaos scripts exit 0

---

### Gate 17: `hardening_provenance_strict`

**Purpose:** All provenance records satisfy schema requirements.

**Implementation:**
- Inline validation: create provenance records via ProvenanceTracker, verify required fields
- Validates: memory_id non-empty, source_type non-empty, tracked_at parseable
- Tests perception provenance rejects empty required fields (scene_id, correlation_id, trigger, model_used)

**Threshold:** 0 invalid records, all validation errors caught

---

## Verdict Logic

```
PROMOTE if all 17 gates PASS
BLOCK  if any gate FAIL
```

Report includes per-gate timing, pass/fail, detail string, and overall verdict.
