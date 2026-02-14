# v2.8.0 Upgrade Notes -- Deterministic Operations

**Release:** v2.8.0 GA
**Tag:** `v2.8.0` at `fbf869a2`
**RC:** `v2.8.0-rc1` at `f39689a3`
**Behavior delta RC to GA:** none (GA commit adds only test/script/doc artifacts)
**Predecessor:** v2.7.0

---

## Four Operational Guarantees

### 1. Deterministic Barge-In with Cancellation Safety

Model routing calls are wrapped in `ModelCallContext` with proper async cancellation.
When a `control.cancel` event arrives mid-turn, the in-flight model call is cancelled
deterministically with **zero zombie tasks**.

- `cancel()` can be called from any coroutine while `call()` is in-flight
- Pre-cancellation is detected before the call starts
- Post-completion cancellation is a safe no-op
- `TurnCancellationManager` enforces at-most-one-active-turn per session
- New turns automatically cancel previous in-flight turns (barge-in)
- Class-level `_active_contexts` counter is invariant: returns to 0 after every call

**Verified by:** 12 barge-in determinism tests + 8 zombie-task proof tests + 200-cycle
cancellation soak (0 violations, 0 leaked tasks)

### 2. Memory Recall is Budgeted and Auditable Per Turn

Every memory retrieval goes through `MemoryRecallContext` with:

- **Context budget:** 2000-character hard ceiling. Oversized recall is truncated,
  never exceeds the budget. Partial inclusion only if remaining > 50 chars.
- **Audit trail:** Each retrieval gets a unique `query_id` (`mq_xxx`), tracks
  `memory_ids` retrieved, `used_count` after truncation, `elapsed_ms`, and errors.
- **Error isolation:** Memory failures never propagate. Timeout, exception, or
  malformed response all return an empty result with `error` field set.
- **TurnMemoryEnvelope:** Attaches recall + write + tool-memory links to the
  turn's event envelope for full traceability.

**Verified by:** 10 memory budget enforcement tests + 200-cycle adversarial
memory soak (0 budget violations, 84+ truncations handled correctly)

### 3. Perception-Triggered Actions Are Structurally Non-Bypassable

`PerceptionActionGate` is the **single enforcement point** for all perception-driven
actions. It is architecturally impossible to execute a perception action without
passing through the gate.

- `require_confirmation()` always creates a PENDING requirement
- Only `approve()` transitions to APPROVED (one-shot, cannot replay)
- `validate_execution()` is the enforcement point -- raises `ConfirmationBypassError`
  if not approved (not a normal exception, not catchable by standard handlers)
- Stale approvals rejected (TTL enforcement)
- Replayed approvals rejected (EXECUTED state is terminal)
- Cross-session approvals isolated (requirement scoped to session)
- Fabricated requirement IDs rejected
- Max pending limit (50) prevents denial-of-service floods
- Per-action risk classification: medium / high / critical

**Verified by:** 12 bypass attempt tests + 500-cycle perception soak
(0 bypass leaks, 0 queue overflows)

### 4. Operator Session Provides Health + Incident Snapshot as First-Class Artifact

`OperatorSession` wraps gateway sessions with operator-facing UX primitives:

- **Push-to-talk state machine:** IDLE -> LISTENING -> PROCESSING -> RESPONDING
  with validated transitions and barge-in support (RESPONDING -> LISTENING)
- **Subsystem health indicators:** model, memory, perception, action, gateway
  each tracked with health status, latency, error count
- **Incident snapshot export:** `export_incident_snapshot()` produces a complete,
  JSON-serializable diagnostic dump (state, indicators, activity timeline, metrics)
- **Activity timeline:** Bounded (200 entries), records all state transitions,
  turn completions, cancellations, mode changes
- **Input mode management:** push_to_talk / always_on / text_only with
  seamless switching

**Verified by:** 10 operator resilience tests + 300-cycle operator soak with
random subsystem degradation (0 stuck sessions, 0 invalid transitions)

---

## Test Coverage Summary

| Suite | Tests | Status |
|-------|-------|--------|
| RC1 hardening (5 risk surfaces) | 52 | All pass |
| v2.8 milestones (M1-M4) | 104 | All pass |
| v2.8 full regression | 156 | All pass |
| v2.7 backward compat | 163 | All pass |
| v2.6 backward compat | 82 | All pass |
| **Full integration suite** | **565** | **All pass** |

## Soak Results

| Phase | Operations | Result |
|-------|-----------|--------|
| Cancellation (cancel at boundary, storms) | 100 | 0 violations |
| Memory (adversarial payloads, budget stress) | 100 | 0 budget violations |
| Perception (approve/deny/expire/bypass) | 300 | 0 bypass leaks |
| Operator (degradation, barge-in, mode switch) | 200 | 0 stuck sessions |
| **Total** | **700** | **PASS** |

## Promotion Gate

14 gates total, 12 passed, 2 skipped (live-service-only: health check, breaker state).
0 failed. Machine-readable report at `S:\reports\gate-v28\`.

Skipped gates documented in `gate-v28-skipped-addendum.json` with acceptance
criteria and run procedures for staging validation.

## New Modules

| Module | Location | Purpose |
|--------|----------|---------|
| `model_call_context.py` | api-gateway | Cancellable model routing |
| `memory_recall_context.py` | api-gateway | Auditable memory retrieval |
| `perception_action_gate.py` | api-gateway | Bypass-proof confirmation gate |
| `operator_session.py` | api-gateway | UX state machine + incident export |

## Release Artifacts

```
S:\releases\v2.8.0\
  release_manifest.json          -- commit, tag, test totals, SHA-256 hashes
  requirements-frozen.txt        -- pip freeze (45 packages)
  dependency-lock.json           -- SHA-256 locked deps
  CHANGELOG.txt                  -- v2.7.0..v2.8.0 delta
  env/pip-freeze.txt             -- full pip snapshot
  env/conda-list.txt             -- conda environment snapshot
  reports/promotion-gate-report.json
  reports/soak-report.json
  reports/reproducibility-check.json
  incidents/sample-incident-snapshot.json
```

## Branch Hygiene

```
v2.8.0      tag  -> fbf869a2 (GA)
v2.8.0-rc1  tag  -> f39689a3 (feature freeze)
v2.8.x-hotfix    -> branched from v2.8.0 for emergency patches
v2.9-dev         -> branched from v2.8.0 for next cycle
master           -> merged v2.8.0 (full history)
```

## Breaking Changes

None. v2.8.0 is fully backward-compatible with v2.7.0 and v2.6.0.
All 163 v2.7 tests and 82 v2.6 tests pass unchanged.

## Hotfix Lane

`v2.8.x-hotfix` is pre-cut from GA. For emergency patches:

```
git checkout v2.8.x-hotfix
# fix, test, commit
git tag -a v2.8.1 -m "v2.8.1 hotfix: <description>"
```
