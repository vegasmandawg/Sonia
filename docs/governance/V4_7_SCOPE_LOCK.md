# SONIA v4.7 Scope Lock

**Schema:** 14.0
**Baseline:** v4.7-dev (inherits v4.6.0 GA at da8ea57)
**Floor:** 66/66 v4.6 gates GREEN
**Contract pin:** v4.6.0 (unchanged until v4.7 GA)

---

## Epics

### Epic A -- Audit-Chain Integrity

**Objective:** Tamper-evident logging with chained hashes, signed incident
bundle verification, and deterministic replay provenance so every side effect
is traceable back to its originating decision.

**Deliverables:**
1. Hash-chained audit log: each entry includes SHA-256 of prior entry.
   Chain break detection on read. Append-only enforcement.
2. Incident bundle manifest signing: bundles produced by
   `export-incident-bundle.ps1` include a signed manifest with SHA-256
   hashes of all contained files. Verification function validates chain.
3. Replay provenance: each replayed decision carries its original
   correlation ID + replay generation counter. Provenance visible in
   audit trail.
4. Chain integrity test: inject a tampered entry, verify detection fires.
5. Cross-service correlation: audit entries from different services that
   share a correlation ID can be reassembled into a single ordered trace.
6. Audit export: `/v1/audit/export` endpoint returns chain segment with
   integrity proof (first hash, last hash, entry count).

**Gate ownership:** 6 delta gates (A1-A6).

### Epic B -- Policy Determinism Under Concurrency

**Objective:** Eliminate race conditions in approval/task mutations,
enforce idempotency keys on all mutating endpoints, and guarantee strict
ordering across restart boundaries.

**Deliverables:**
1. Approval race hardening: concurrent approve/deny on same confirmation
   ID produces exactly one winner, loser gets 409. No double-approve.
2. Task mutation serialization: concurrent create/delete on same task
   produces deterministic outcome. No phantom tasks.
3. Idempotency keys: all mutating endpoints accept `X-Idempotency-Key`
   header. Duplicate requests return cached result, not re-execution.
4. Idempotency store: durable (SQLite), TTL-bounded, keyed by
   (endpoint, idempotency_key). Survives restart.
5. Restart ordering guarantee: after process restart, restored state
   reflects the exact sequence of pre-crash mutations. No reordering.
6. Fence tokens: approval operations carry monotonic fence token.
   Stale tokens rejected. Prevents ABA problems in approve/deny cycles.

**Gate ownership:** 6 delta gates (B1-B6).

### Epic C -- Runtime SLO Automation

**Objective:** Automated degrade-mode transitions when sustained latency
breaches occur, with operator-visible diagnostics and deterministic
recovery exit criteria.

**Deliverables:**
1. Sustained breach detection: p95/p99 exceeding threshold for N
   consecutive windows (configurable, default 3) triggers degrade mode.
   Single-spike transients do not trigger.
2. Degrade-mode transition: when triggered, system sheds non-essential
   work (vision frames, low-priority memory writes) and emits
   `slo.degrade.entered` event with reason and metrics snapshot.
3. Recovery exit criteria: degrade mode exits only after M consecutive
   healthy windows (configurable, default 5). Premature exit blocked.
   Emits `slo.degrade.exited` event.
4. Operator diagnostics: `/v1/slo/status` returns current mode
   (normal/degraded), breach history, time-in-degrade, and
   clear-to-recover flag.
5. Chaos: sustained latency injection triggers degrade, removal triggers
   recovery. Full cycle tested.
6. SLO configuration: thresholds and window sizes configurable via
   `sonia-config.json` under `slo` key. Changes take effect without
   restart.

**Gate ownership:** 6 delta gates (C1-C6).

---

## Explicit Non-Goals (v4.7)

- **Kubernetes / container orchestration.** Deferred to packaging epic.
- **Multi-user cloud tenancy.** Single-operator only.
- **Electron shell / native UI.** Desktop packaging is v5.x.
- **Breaking contract changes.** SONIA_CONTRACT stays at v4.6.0 unless
  explicitly approved.
- **New service additions.** No new microservices in v4.7.
- **Speculative feature expansion.** No features outside these three epics.

---

## Invariants

1. **Floor regression zero-tolerance.** All 66 inherited v4.6 gates must pass
   at every merge point. Any floor regression blocks promotion.
2. **Audit chain integrity.** After Epic A, any tampered log entry must be
   detected on read. Silent corruption is a promotion blocker.
3. **Concurrency determinism.** After Epic B, concurrent mutations on the same
   resource must produce exactly one winner. Double-execution is a promotion
   blocker.
4. **SLO automation closed-loop.** After Epic C, sustained breaches must
   trigger degrade mode and recovery must be automatic. Manual intervention
   required for SLO response is a promotion blocker.
5. **Contract pin.** SONIA_CONTRACT stays at v4.6.0 until GA.
6. **Fail-closed inheritance.** All fail-closed semantics from v4.6 (auth
   startup, budget store degradation) must remain operative.

---

## Rollback Policy

- **Pre-merge:** `git checkout v4.7-dev && git reset --hard v4.6.0` restores
  baseline. No side effects.
- **Post-merge pre-GA:** `git revert --no-ff <merge-commit>` on v4.7-dev.
  Re-run 66-gate floor to confirm clean revert.
- **Post-GA:** hotfix on `release/v4.7.x`, never force-push tags.
- **Data migration:** Epic B introduces idempotency store (new SQLite table).
  Rollback drops the table; no existing data affected.

---

## Gate Architecture

- **Floor:** 66 gates inherited from v4.6 (schema 13.0)
- **Delta:** 18 new gates (6 per epic)
- **Total:** 84 gates
- **Script:** `scripts/release/gate-v47.py`
- **Report:** `releases/v4.7.0/gate-report.json`

---

## Delta Gate Map

| ID | Epic | Gate Name | Checks |
|----|------|-----------|--------|
| A1 | A | audit-chain-present | Hash-chained audit log exists |
| A2 | A | chain-tamper-detection | Tampered entry detected on read |
| A3 | A | bundle-manifest-signed | Incident bundle includes signed manifest |
| A4 | A | replay-provenance | Replay carries original correlation + generation |
| A5 | A | cross-service-trace | Shared correlation IDs reassemble into trace |
| A6 | A | audit-export-endpoint | /v1/audit/export returns chain with proof |
| B1 | B | approval-race-safe | Concurrent approve/deny = exactly one winner |
| B2 | B | task-mutation-serial | Concurrent task ops = deterministic outcome |
| B3 | B | idempotency-key-support | X-Idempotency-Key accepted on mutating endpoints |
| B4 | B | idempotency-store-durable | Idempotency store survives restart |
| B5 | B | restart-ordering-strict | Restored state reflects exact pre-crash sequence |
| B6 | B | fence-token-enforcement | Stale fence tokens rejected on approve/deny |
| C1 | C | sustained-breach-detect | Transient spike no trigger, sustained does |
| C2 | C | degrade-mode-transition | Breach triggers degrade + event emission |
| C3 | C | recovery-exit-criteria | Recovery requires M consecutive healthy windows |
| C4 | C | slo-diagnostics-endpoint | /v1/slo/status returns mode + breach history |
| C5 | C | chaos-degrade-cycle | Injection triggers degrade, removal recovers |
| C6 | C | slo-config-dynamic | Threshold changes take effect without restart |

---

## Gap Closure Evidence

### Baseline (pre-implementation)
- Floor: 66/66 PASS
- Delta: 15/18 PASS (B4 idempotency-store-durable FAIL, C3 recovery-exit-criteria FAIL, C4 slo-diagnostics-endpoint FAIL)

### Post-closure
- Floor: 66/66 PASS (zero regressions)
- Delta: 18/18 PASS
- **VERDICT: PROMOTE (84/84)**

### Gap Implementations
- **B4 idempotency-store-durable**: `idempotency_keys` table in DurableStateStore (SQLite WAL, TTL-expiring, write-through). 7 tests.
- **C3 recovery-exit-criteria**: `SLOGuardrails` class in `latency_budget.py` -- 3-state machine (NORMAL/DEGRADED/RECOVERING), M consecutive_healthy windows to exit_degrade, clear_to_recover flag. 6 tests.
- **C4 slo-diagnostics-endpoint**: `GET /v1/slo/status` + `/v3/slo/status` -- returns current_mode, breach_history, time_in_degrade, degrade_reason, clear_to_recover. 2 tests.
- **Epic A**: 6/6 at baseline, no implementation needed.

### B4 fail-closed note
DurableStateStore idempotency methods follow existing pattern: persistence failures log warnings but never raise. Expired keys return None (fail-closed: no cached result = full re-execution).

---

## Execution Choreography

1. `v4.7-m0-scope-lock` -- this commit (scope lock + gate scaffold + baseline)
2. `v4.7-epic-a-audit-chain` -- tests first, then implementation
3. `v4.7-epic-b-concurrency` -- tests first, then implementation
4. `v4.7-epic-c-slo-automation` -- tests first, then implementation
5. Merge each epic with `--no-ff` only after its 6/6 delta gates pass
6. Final: full 84-gate run + soak + clean-room parity + bundle hashes
