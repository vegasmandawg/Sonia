# V3.2 Scope Lock -- M1 Decision Set

**Branch**: `v3.2-dev`
**Base**: `v3.1.0` (stabilization baseline)
**Version**: `SONIA_VERSION = "3.2.0-dev"`
**Contract posture**: API contract frozen at `v3.0.0` for this milestone.
**Stability floor**: inherit v3.1 hardening gates unchanged; no gate removals.
**Governance posture**: no silent side effects, no bypass paths, full audit continuity.
**Locked**: 2026-02-15

---

## Selected Epics

| Epic | Role | Scope |
|------|------|-------|
| **A: Voice Session Quality and Turn Determinism** | Primary | Full |
| **B: Perception -> Confirmation Ergonomics** | Primary | Full |
| **C: Memory Ops Governance** | Limited | Phase-0 only |

A+B are the highest leverage for companion quality. C is included only to
prevent governance debt from accumulating while A+B expand throughput.

---

## What Is In Scope (v3.2 M1)

### Epic A: Voice Session Quality and Turn Determinism
- Streaming turn pipeline refinements for lower perceived latency
- Deterministic barge-in/cancel semantics across replay
- Clear state transitions in voice turn lifecycle (start, partial, interrupt, resume, commit)

### Epic B: Perception -> Confirmation Ergonomics
- Perception event dedupe and priority routing before confirmation
- Confirmation queue ergonomics under burst load (batching + one-shot semantics preserved)
- SceneAnalysis schema compatibility checks without contract drift

### Epic C Phase-0 Only
- Memory write proposal/approval primitives (backend + audit path)
- Rejection/retraction APIs and provenance guarantees
- No full operator memory UI in M1 (that becomes M2+)

---

## What Is Explicitly Out of Scope (Freeze List)

- No API contract version bump
- No broad memory editor UX
- No new external integrations that alter trust boundaries
- No speculative optimization that bypasses audit or confirmation checks
- No release-branch feature backports (`release/v3.1.x` remains bugfix/security-only)

---

## Gate Model (gate-v32.py)

v3.1 stability floor (17 gates) + 6 new v3.2 gates = **23 total**.

### Inherited Gates (1-17)
All v3.1 gates unchanged. See `docs/V3_1_GATE_SPEC.md` for details.

### New Gates (18-23)

| Gate | Name | Pass Criteria |
|------|------|---------------|
| G18 | Voice latency budget | p95 warm-path turn latency <= 1200 ms (speech detected -> first assistant token) |
| G19 | Barge-in replay determinism | 100% deterministic replay across defined fixture set |
| G20 | Perception dedupe correctness | Zero false bypass, deterministic merge decisions |
| G21 | Confirmation storm integrity | Zero bypass attempts, zero double-consume, queue bounds respected |
| G22 | Memory proposal governance | Zero direct-write bypass, complete provenance chain for all attempts |
| G23 | Memory replay integrity | No orphaned entries, no timeline corruption, deterministic final state |

---

## Test Inventory Target (M1)

| Suite | Location | Target Count |
|-------|----------|-------------|
| Epic A (voice) | `tests/v32_voice/` | 12-16 |
| Epic B (perception) | `tests/v32_perception/` | 12-16 |
| Epic C Phase-0 (memory ops) | `tests/v32_memory_ops/` | 10-14 |
| **Net new** | | **34-46** |

No reduction in existing hardening coverage (151 baseline).

---

## Operational Acceptance Criteria (M1)

- v3.1 floor gates: unchanged and green
- New v3.2 gates (G18-G23): all green
- Regression + hardening + new tests: all pass
- One medium soak run with zero invariant violations
- One chaos subset run focused on A/B/C failure modes
- Artifact manifest hashes match for milestone bundle
- Cleanroom smoke passes on milestone tag

---

## Execution Order

| Phase | Days | Work |
|-------|------|------|
| Phase 1 | 1-2 | **A foundation**: deterministic turn state transitions, cancellation contract, replay fixtures |
| Phase 2 | 3-5 | **B pipeline**: dedupe, priority lanes, confirmation queue constraints, burst handling |
| Phase 3 | 6-7 | **C governance Phase-0**: proposal/approval/reject/retract primitives, provenance, replay tests |
| Phase 4 | 8-10 | **Gate hardening + soak**: finalize gate-v32.py, regression + hardening + soak + chaos subset |

---

## Commit Cadence

```
docs(v3.2): lock M1 scope for epics A/B + C phase-0, freeze non-goals
feat(voice): deterministic turn lifecycle and barge-in cancel semantics
test(voice): replay determinism and latency budget fixtures
feat(perception): dedupe/priority confirmation routing under load
test(perception): storm integrity and one-shot consumption invariants
feat(memory): proposal/approval governance primitives with provenance
test(memory): ledger replay/recovery integrity phase-0
gate(v3.2): add G18-G23 on top of v3.1 stability floor
release(v3.2-m1): milestone bundle + hash manifest + reports
```

---

## Epic A: Strict Transition Matrix

State x Event -> (Next State, Commands). Any cell marked `--` is an illegal
transition that the reducer absorbs with `EmitDiagnostic`.

| Current State | TURN_STARTED | ASR_PARTIAL | ASR_FINAL | MODEL_FIRST_TOKEN | MODEL_STREAM_ENDED | TTS_STARTED | TTS_CHUNK | TTS_ENDED | BARGE_IN_REQUESTED | CANCEL_REQUESTED | CANCEL_ACK | TURN_TIMEOUT | TURN_FAILED |
|---------------|-------------|-------------|-----------|-------------------|-------------------|-------------|-----------|-----------|-------------------|-----------------|------------|-------------|-------------|
| **IDLE** | LISTENING [StartASR] | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| **LISTENING** | -- | LISTENING | THINKING [StartModel] | -- | -- | -- | -- | -- | -- | -- | -- | ABORTED | ERROR |
| **THINKING** | -- | -- | -- | SPEAKING [StartTTS] | -- | -- | -- | -- | INTERRUPTING [CancelModel] | -- | -- | ABORTED | ERROR |
| **SPEAKING** | -- | -- | -- | -- | SPEAKING | SPEAKING | SPEAKING | COMPLETED | INTERRUPTING [CancelTTS] | -- | -- | ABORTED | ERROR |
| **INTERRUPTING** | -- | absorb | absorb | absorb | absorb | absorb | absorb | absorb | absorb | CANCELLING | CANCELLING | ABORTED | ERROR |
| **CANCELLING** | LISTENING [re-entry] | absorb | absorb | absorb | absorb | absorb | absorb | absorb | absorb | absorb | absorb (ack) | ABORTED | ERROR |
| **COMPLETED** | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag |
| **ABORTED** | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag |
| **ERROR** | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag | absorb+diag |

**Key**:
- `[CommandName]` = command emitted as side-effect intent
- `absorb` = event consumed silently (stale during transition)
- `absorb+diag` = terminal state absorbs with `EmitDiagnostic` command
- `--` = illegal transition, raises or absorbs depending on context

**Determinism rules** (8 invariants, all enforced in `turn_reducer.py`):
1. Strictly monotonic `seq` -- reject if `event.seq <= snapshot.seq`
2. Pure function -- `reduce_turn(snapshot, event) -> (snapshot, commands)`, no I/O
3. Commands are intent declarations, not executed in reducer
4. Idempotent command execution via composite key `session:turn:seq:command_name`
5. Terminal states (COMPLETED, ABORTED, ERROR) absorb all subsequent events
6. Barge-in always routes through INTERRUPTING -> CANCELLING -> LISTENING
7. Cancel token is one-shot: request once, consume once per (session_id, turn_id)
8. `deterministic_hash()` excludes wall-clock, includes state/seq/terminal/reason/flags

---

## Phase Completion Status

### Phase 1: Epic A -- Voice Turn Determinism (COMPLETE)

**Commits**: 6 (8154171..0ff83c0)
**Tests**: 24/24 PASS (0.08s)
**Gates**: G18 PASS, G19 PASS

Modules delivered:
- `services/voice/voice_turn_state.py` -- FSM with strict transition matrix
- `services/voice/voice_turn_reducer.py` -- pure-function reducer (state, event) -> (state, effects)
- `services/voice/voice_cancel_registry.py` -- bounded cancel tokens, one-shot semantics
- `services/voice/voice_latency_tracker.py` -- per-phase latency with percentile reporting

Test suites:
- `tests/v32_voice/test_turn_lifecycle.py` (8 tests)
- `tests/v32_voice/test_replay_determinism.py` (5 tests)
- `tests/v32_voice/test_bargein_cancel_semantics.py` (7 tests)
- `tests/v32_voice/test_latency_budget_g18.py` (4 tests)

### Phase 2: Epic B -- Perception -> Confirmation Ergonomics (COMPLETE)

**Commits**: 5 (da8af27..bf43d2b)
**Tests**: 23/23 PASS (0.25s)
**Gates**: G20 PASS, G21 PASS

Modules delivered:
- `services/perception/event_normalizer.py` -- canonical PerceptionEnvelope, stable dedupe_key
- `services/perception/dedupe_engine.py` -- window-bounded exact/near-duplicate detection
- `services/perception/priority_router.py` -- P0/P1/P2 lanes, strict preemption, weighted round-robin
- `services/perception/confirmation_batcher.py` -- one-shot confirmation, throttle-not-bypass
- `services/perception/provenance_hooks.py` -- append-only audit chain, deterministic hash
- `services/perception/policy.py` -- pipeline orchestrator (normalize -> dedupe -> route -> confirm)

Test suites:
- `tests/v32_perception/test_dedupe_correctness.py` (7 tests)
- `tests/v32_perception/test_priority_routing.py` (8 tests)
- `tests/v32_perception/test_confirmation_storm_integrity.py` (8 tests)

### Phase 3: Epic C -- Memory Ops Governance (COMPLETE)

**Commits**: 5 (b235edd..c8e30af)
**Tests**: 30/30 PASS (0.23s)
**Gates**: G22 PASS, G23 PASS

Modules delivered:
- `services/memory_ops/proposal_model.py` -- MemoryProposal envelope, 7-state FSM, strict transitions
- `services/memory_ops/proposal_policy.py` -- risk tier classifier (auto_low / guarded_medium / guarded_high)
- `services/memory_ops/proposal_queue.py` -- bounded queue (MAX_PENDING=50), one-shot decisions
- `services/memory_ops/conflict_detector.py` -- 4 conflict types, explicit resolution required
- `services/memory_ops/provenance.py` -- append-only governance audit chain, deterministic hash
- `services/memory_ops/governance_pipeline.py` -- orchestrator (propose -> classify -> conflict -> queue -> decide -> apply)
- `services/memory_ops/replay_engine.py` -- deterministic replay verifier, hash comparison

Test suites:
- `tests/v32_memory_ops/test_proposal_governance.py` (16 tests)
- `tests/v32_memory_ops/test_replay_determinism.py` (14 tests)

Invariants enforced:
- No silent writes (silent_write_count == 0)
- Proposal requires approval for guarded tiers
- Replay produces identical hashes for same input
- Conflicts surfaced explicitly, never auto-merged
- Append-only provenance with deterministic chain hash

### Gate Summary (as of c8e30af)

| Gate | Status | Tests |
|------|--------|-------|
| G18 | PASS | 4/4 |
| G19 | PASS | 12/12 |
| G20 | PASS | 15/15 |
| G21 | PASS | 8/8 |
| G22 | PASS | 16/16 |
| G23 | PASS | 14/14 |
| G08 | KNOWN FAILURE | Requires live services (not a regression) |

**Combined v3.2 floor**: 77/77 PASS in 0.27s

---

## Entry Criteria

- [x] `v3.2-dev` branch off `v3.1.0` tag
- [x] `SONIA_VERSION = "3.2.0-dev"`
- [x] Scope lock document written and locked
- [x] `gate-v32.py` scaffolded (v3.1 gates as stability floor + G18-G23 stubs)
- [x] Epic selection committed
- [x] Test directories created

## Exit Criteria

- All v3.1 regression tests pass (151 baseline)
- All v3.2 M1 tests pass (34-46 new)
- Gate-v32 promotion: 23/23 gates PASS
- No contract drift (`SONIA_CONTRACT` still `v3.0.0`)
- Milestone bundle archived with SHA-256 manifest
