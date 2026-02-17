# SONIA v4.6 Scope Lock

**Schema:** 13.0
**Baseline:** v4.6-dev (inherits v4.5.0 GA at c19a2a3)
**Floor:** 48/48 v4.5 gates GREEN
**Contract pin:** v4.5.0 (unchanged until v4.6 GA)

---

## Epics

### Epic A — Authenticated Operator Boundary

**Objective:** Require authenticated identity for all mutating endpoints with
fail-closed enforcement, role-based access (operator vs observer), token
rotation, and actor attribution in every audit record.

**Deliverables:**
1. Auth middleware on all mutating endpoints (`/tasks`, `/approve`, tool
   execution, policy toggles). Read-only diagnostics remain open.
2. Role split: `operator` (mutate/approve) and `observer` (read-only
   diagnostics). Role enforcement matrix tested per endpoint.
3. Token/key rotation with explicit invalidation window. Prior token set
   becomes invalid after rotation window closes.
4. Actor attribution in every side-effect log record and approval record.
   Every audit entry includes `actor_id` and `actor_role`.
5. Fail-closed startup: if auth policy is enabled but key material is
   missing or invalid, service refuses to start.

**Gate ownership:** 6 delta gates (A1-A6).

### Epic B — Persistent Control Plane

**Objective:** Move task store, approval state, and supervisor restart budgets
from in-memory to durable WAL-backed storage with idempotent replay and
deterministic restore ordering.

**Deliverables:**
1. Task store backed by durable WAL storage. Tasks persist across process
   restarts.
2. Approval state (pending confirmations + TTL) restored from durable store
   on boot.
3. Supervisor restart-window counters and backoff state persisted across
   process restarts.
4. Idempotent outbox replay for control-plane writes (duplicate replay
   produces no side effects).
5. Deterministic restore order: sessions -> confirmations -> tasks ->
   restart budgets.
6. Migration forward/backward integrity: schema upgrades preserve existing
   data; downgrades are safe.

**Gate ownership:** 6 delta gates (B1-B6).

### Epic C — Runtime Reliability Budgets

**Objective:** Global backpressure enforcement across all ingress paths,
hard SLO enforcement with degrade mode, chaos testing for partial failures,
and incident replay determinism.

**Deliverables:**
1. Global backpressure policy across stream ingress + tool queue + model
   queue. Shed oldest-first when capacity exceeded.
2. Hard SLO enforcement: degrade mode triggers when p95/p99 breach
   sustained thresholds. Automatic recovery when metrics return to bounds.
3. Chaos tests: service flap recovery (rapid up/down cycles).
4. Chaos tests: partial dependency outage recovery (single service down).
5. Incident snapshot replay determinism: same input envelope produces the
   same decision trace class.
6. Queue storm resistance: burst of 100+ concurrent requests handled
   gracefully without data loss.

**Gate ownership:** 6 delta gates (C1-C6).

---

## Explicit Non-Goals (v4.6)

- **Kubernetes / container orchestration.** Still deferred to packaging epic.
- **Multi-user cloud tenancy.** Single-operator only. Multi-tenant is v5.x.
- **Speculative feature expansion.** No features outside these three epics.
- **Breaking contract changes.** SONIA_CONTRACT stays at v4.5.0 unless
  explicitly approved.
- **Electron shell / native UI.** Desktop packaging is v4.7+.

---

## Invariants

1. **Floor regression zero-tolerance.** All 48 inherited v4.5 gates must pass
   at every merge point. Any floor regression blocks promotion.
2. **Fail-closed auth.** If auth policy is enabled, missing/invalid credentials
   must prevent service startup. No silent fallback to unauthenticated mode.
3. **Durable state survival.** After Epic B, all control-plane state must
   survive process restart. In-memory-only state is a promotion blocker.
4. **SLO enforcement path.** After Epic C, sustained latency breaches must
   trigger observable degrade mode. Silent degradation is a promotion blocker.
5. **Contract pin.** SONIA_CONTRACT stays at v4.5.0 until GA.

---

## Gate Architecture

- **Floor:** 48 gates inherited from v4.5 (schema 12.0)
- **Delta:** 18 new gates (6 per epic)
- **Total:** 66 gates
- **Script:** `scripts/release/gate-v46.py`
- **Report:** `releases/v4.6.0/gate-report.json`

---

## Gap Closure Evidence

### Baseline (pre-implementation)
- Floor: 48/48 PASS
- Delta: 16/18 PASS (A3 role-enforcement FAIL, B3 supervisor-budget-persist FAIL)

### A3 — Role Enforcement (closed)
- **Branch:** `v4.6-epic-a-role-enforcement` (commit 23d400c)
- **Implementation:** `Role` enum (OPERATOR/OBSERVER), `require_role()` decorator in `auth.py`
- **AuthMiddleware:** `request.state.user_role` set on all auth paths
- **Tests:** `tests/integration/test_role_enforcement.py` (7 tests, all green)
- **Merged:** `--no-ff` into `v4.6-dev`

### B3 — Supervisor Budget Persistence (closed)
- **Branch:** `v4.6-epic-b-supervisor-budget-persistence` (commit b6b2c6f)
- **Implementation:** `RestartBudgetStore` (SQLite WAL) in `service_supervisor.py`
- **Schema:** `restart_budgets` table (service_name PK, window_start_ms, attempt_count, backoff_until_epoch_ms, exhausted, updated_at)
- **Write-through:** record_attempt, update_backoff, mark_exhausted, prune_expired
- **Fail-closed:** corrupted DB enters degraded mode (synthetic exhausted budget, attempt_count=999) -- prevents permissive reset
- **Tests:** `tests/integration/test_supervisor_budget_persist.py` (7 tests, all green)
- **Merged:** `--no-ff` into `v4.6-dev`

### Final Gate Run
- **Result:** 66/66 PASS, PROMOTE
- **Floor regressions:** 0
- **Integration tests:** 14/14 green (7 A3 + 7 B3)
