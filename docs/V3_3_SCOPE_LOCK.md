# v3.3 Scope Lock

**Status**: M0 LOCKED -- epics defined, gates specified, ready for feature branches
**Branch**: `v3.3-dev`
**Base**: v3.2.0 GA (`07879ed`)
**M0 commit**: `5cac8a6` (last freeform commit; everything after maps to an epic)
**Contract**: SONIA_CONTRACT pinned at `v3.0.0` (no breaking changes)

---

## 1. Objectives

Three epics selected per criteria: operator value, testability, blast radius, evidence, dependencies.

| Epic | Name | Gates | Scope Summary |
|------|------|-------|---------------|
| A | Memory Ledger Operations v2 | G24/G25 | Ledger edits, redaction, provenance slicing, retrieval traceability |
| B | Recovery + Incident Tooling | G26/G27 | EVA-OS drills, restore verification, chaos broadening, operator triage |
| C | Perception Privacy Hardening | G28/G29 | Privacy boundary states, zero-frame enforcement, confirmation non-bypass |

### Epic A: Memory Ledger Operations v2

**Objective**: Expand memory governance beyond propose/approve/apply to cover edits,
merges, redaction, export/import, conflict surfacing, and "why was this retrieved?"
traceability.

**Modules** (under `services/memory_ops/`):
- `ledger_editor.py` -- edit/merge operations with full provenance
- `redaction_engine.py` -- deterministic redaction with audit trail
- `provenance_slicer.py` -- "why retrieved?" query path with chain extraction
- `export_import.py` -- ledger export/import with integrity verification

**Tests** (under `tests/v33_memory_ops/`):
- G24: `test_ledger_edit_governance.py` (>=14 tests)
- G25: `test_redaction_provenance.py` (>=12 tests)

**Contract impact**: None. All operations are additive to existing ledger. No envelope
schema changes. MemoryProposal envelope gains optional `edit_type` field (backward compatible).

### Epic B: Recovery + Incident Tooling

**Objective**: Expand EVA-OS incident bundles, add automated triage recommendations,
strengthen restore verification, broaden chaos suite, add reproducible operator drills.

**Modules** (under `services/eva_os/` and `scripts/chaos/`):
- `services/eva_os/triage_recommender.py` -- automated triage from incident snapshots
- `services/eva_os/restore_verifier.py` -- post-restore invariant checks
- `services/eva_os/operator_drill.py` -- reproducible drill framework
- `scripts/chaos/chaos_v33_*.py` -- expanded chaos scenarios

**Tests** (under `tests/v33_recovery/`):
- G26: `test_restore_integrity.py` (>=12 tests)
- G27: `test_incident_triage.py` (>=10 tests)

**Contract impact**: None. EVA-OS internal; no public API changes.

### Epic C: Perception Privacy Hardening

**Objective**: Add explicit privacy boundary states to perception pipeline, enforce
zero-frame invariant under all code paths, harden confirmation non-bypass under
concurrency and malformed envelopes.

**Modules** (under `services/perception/`):
- `privacy_gate.py` -- privacy boundary state machine (CAPTURING/SUSPENDED/BLOCKED)
- `zero_frame_enforcer.py` -- deterministic zero-frame guarantee
- Enhanced `confirmation_batcher.py` -- malformed envelope rejection, concurrency hardening

**Tests** (under `tests/v33_perception/`):
- G28: `test_privacy_boundary.py` (>=12 tests)
- G29: `test_zero_frame_confirmation.py` (>=10 tests)

**Contract impact**: None. Perception pipeline internal. No event envelope changes.
Privacy states are internal to perception service.

---

## 2. Non-Goals (hard exclusions)

- **No contract breaking changes**: SONIA_CONTRACT stays at `v3.0.0`
- **No v3.2 module modifications**: bugfixes go to `release/v3.2.x` only
- **No new external dependencies**: all deps must be mirrored/frozen and reproducible
- **No changes to core boot sequence**: port assignments and service startup order unchanged
- **No "always-on cloud" flows**: network remains policy-controlled, explicit, logged
- **No unbounded UI scope**: UI changes (if any) must be incremental, testable, behind feature flags
- **No data migrations without rollback**: any state schema change requires rollback script + invariant tests
- **No toolchain upgrades**: Python version, pytest version, and all pinned deps stay frozen

---

## 3. Contract Policy

`SONIA_CONTRACT` remains pinned at `v3.0.0`. If any epic requires a contract bump,
it must be called out as a separate scope item with migration path documented before
approval. No epic in this scope lock requires a bump.

All additive fields (e.g., `edit_type` on MemoryProposal) must be optional with
sensible defaults. Existing consumers must not break.

---

## 4. Gate Map

### Inherited Floor (v3.2, mandatory -- must remain green)

| Gate | Suite | Tests | Origin |
|------|-------|-------|--------|
| G18 | test_latency_budget_g18.py | 4 | v3.2 Epic A |
| G19 | test_bargein_cancel_semantics.py + test_replay_determinism.py + test_turn_lifecycle.py | 20 | v3.2 Epic A |
| G20 | test_dedupe_correctness.py + test_priority_routing.py | 15 | v3.2 Epic B |
| G21 | test_confirmation_storm_integrity.py | 8 | v3.2 Epic B |
| G22 | test_proposal_governance.py | 16 | v3.2 Epic C |
| G23 | test_replay_determinism.py (memory_ops) | 14 | v3.2 Epic C |

**Inherited floor total: 77 tests**

### Delta Gates (v3.3)

#### G24 -- Ledger Edit Governance (Epic A)

| Field | Value |
|-------|-------|
| Purpose | Prove that ledger edits (update, merge, redact) follow governed paths with full provenance |
| Input | Fixture set of edit/merge/redact operations across all memory subtypes |
| Command | `python -m pytest tests/v33_memory_ops/test_ledger_edit_governance.py -v` |
| Pass criteria | >= 14 passed, 0 failed; zero direct-edit bypass; provenance chain complete for every mutation |
| Evidence | `S:\reports\gate-v33\g24\` (test output + provenance chain dump) |
| Owner | Epic A |

#### G25 -- Redaction + Provenance Slicing (Epic A)

| Field | Value |
|-------|-------|
| Purpose | Prove redaction is deterministic, auditable, and provenance queries return accurate chains |
| Input | Fixture set of redaction requests + "why retrieved?" queries |
| Command | `python -m pytest tests/v33_memory_ops/test_redaction_provenance.py -v` |
| Pass criteria | >= 12 passed, 0 failed; redacted content irrecoverable; provenance slice matches ground truth |
| Evidence | `S:\reports\gate-v33\g25\` (test output + redaction audit log) |
| Owner | Epic A |

#### G26 -- Restore Integrity (Epic B)

| Field | Value |
|-------|-------|
| Purpose | Validate that recovery paths restore coherent state without violating invariants |
| Input | Backup/restore roundtrips, restart storms, dependency graph transitions (DEGRADED->RECOVERING->HEALTHY) |
| Command | `python -m pytest tests/v33_recovery/test_restore_integrity.py -v` |
| Pass criteria | >= 12 passed, 0 failed; restore roundtrip produces identical state hashes; services converge to HEALTHY |
| Evidence | `S:\reports\gate-v33\g26\` (restore artifacts + state hash comparison) |
| Owner | Epic B |

#### G27 -- Incident Triage Automation (Epic B)

| Field | Value |
|-------|-------|
| Purpose | Prove incident bundle export/import works and triage recommendations are reproducible |
| Input | Synthetic incident scenarios with known root causes; operator drill fixtures |
| Command | `python -m pytest tests/v33_recovery/test_incident_triage.py -v` |
| Pass criteria | >= 10 passed, 0 failed; bundle roundtrip intact; triage recommendations match expected for known scenarios |
| Evidence | `S:\reports\gate-v33\g27\` (incident bundles + triage report) |
| Owner | Epic B |

#### G28 -- Privacy Boundary Enforcement (Epic C)

| Field | Value |
|-------|-------|
| Purpose | Prove perception pipeline enforces privacy boundaries with no bypass paths |
| Input | State machine transitions (CAPTURING/SUSPENDED/BLOCKED), malformed envelopes, concurrency bursts |
| Command | `python -m pytest tests/v33_perception/test_privacy_boundary.py -v` |
| Pass criteria | >= 12 passed, 0 failed; 0 successful bypasses; all attempts logged with correct failure taxonomy |
| Evidence | `S:\reports\gate-v33\g28\` (test output + bypass attempt log) |
| Owner | Epic C |

#### G29 -- Zero-Frame + Confirmation Hardening (Epic C)

| Field | Value |
|-------|-------|
| Purpose | Prove zero-frame guarantee holds under all code paths and confirmation cannot be bypassed via replay/races |
| Input | Zero-frame scenarios, replay attempts, UI ACK races, concurrent confirmation bursts |
| Command | `python -m pytest tests/v33_perception/test_zero_frame_confirmation.py -v` |
| Pass criteria | >= 10 passed, 0 failed; zero frames emitted during BLOCKED state; zero double-consume; zero replay bypass |
| Evidence | `S:\reports\gate-v33\g29\` (test output + invariant summary) |
| Owner | Epic C |

### Gate Ownership Table

| Epic | Gates Changed | Tests Added | Modules Touched |
|------|---------------|-------------|-----------------|
| A (Memory Ledger v2) | G24, G25 | >= 26 | memory_ops/ledger_editor, redaction_engine, provenance_slicer, export_import |
| B (Recovery + Incident) | G26, G27 | >= 22 | eva_os/triage_recommender, restore_verifier, operator_drill; scripts/chaos/ |
| C (Perception Privacy) | G28, G29 | >= 22 | perception/privacy_gate, zero_frame_enforcer, confirmation_batcher (enhanced) |

**Delta total: >= 70 tests across 6 gates**
**Combined floor: >= 147 tests (77 inherited + 70 delta)**

---

## 5. Risk Register

| # | Risk | Likelihood | Impact | Detection Gate | Mitigation | Rollback |
|---|------|-----------|--------|----------------|------------|----------|
| R1 | Floor regression from new feature code | Medium | High | FLOOR_v32_77 in gate-v33.py | Full v3.2 floor runs before delta gates; any failure blocks promotion | Revert feature commit, rerun floor |
| R2 | Hidden nondeterminism from concurrency in new pipelines | Medium | High | G28, G29 (concurrency burst tests) | Replay harness verifies hash stability across N runs; soak includes concurrency phases | Disable new pipeline behind feature flag |
| R3 | Gate drift (tests added but not wired into release script) | Medium | Medium | G29 (release discipline) | gate-v33.py auto-discovers test dirs; gate wiring is first commit per epic | Manual audit of gate-v33.py before RC tag |
| R4 | Performance regression from new logging/provenance instrumentation | Low | Medium | Soak p95 budgets | Provenance writes are append-only with bounded buffers; soak measures latency | Remove instrumentation, fall back to v3.2 provenance |
| R5 | Recovery regressions from new state machine transitions | Medium | High | G26, G27 (restore roundtrip + restart storms) | EVA-OS state machine is isolated; new transitions are additive only | Revert EVA-OS changes; supervisor falls back to v3.2 behavior |
| R6 | Contract bump pressure from new memory operations | Low | High | G24 (contract compatibility check in test) | All new fields are optional; existing consumers tested for backward compat | Remove additive fields; revert to v3.2 proposal model |
| R7 | Feature flag leakage (disabled features affecting code paths) | Low | Medium | Floor gates (if leakage causes regression, floor catches it) | Feature flags are checked at entry point; no conditional logic deep in pipelines | Remove feature flag checks entirely; clean revert |
| R8 | Branch contamination of release/v3.2.x | Low | High | Manual review | Only bugfix/security branches; cherry-pick with traceability | Git revert on release branch |

---

## 6. Promotion Criteria (binary -- all must be true)

- [ ] **Inherited floor**: G18-G23 all PASS (77/77)
- [ ] **Delta gates**: G24-G29 all PASS
- [ ] **Combined floor**: >= 147 tests (77 + 70 delta), 0 failures
- [ ] **Cross-epic soak**: all invariants ZERO (inherited + new)
  - Inherited: silent_write_count, false_bypass_count, replay_divergence_count, voice_cancel_violations, illegal_transition_attempts, double_decision_attempts, conflict_unsurfaced_count
  - New: direct_edit_bypass_count, redaction_leak_count, restore_state_mismatch_count, privacy_bypass_count, zero_frame_violation_count
- [ ] **Clean-room parity**: all gates PASS from tagged RC (not just dev branch)
- [ ] **Release bundle**: all artifacts present, SHA-256 manifest verified
  - Required: release-manifest.json, gate-report.json, soak-report.json, scope-lock.md, CHANGELOG.md, requirements-frozen.txt, rollback-notes.md
- [ ] **No SONIA_CONTRACT bump** unless separately approved
- [ ] **No SLO violations**: soak p95 within budgets (voice < 1200ms, memory < 500ms, perception < 300ms)

---

## 7. Release Branch Policy

### release/v3.2.x (maintenance)
- Only `bugfix/*` and `security/*` branches may merge
- Require PR + CI gate + at least one reviewer
- Cherry-pick only from `main`/`v3.3-dev` with traceability: `(cherry-picked from <sha>)`
- Patch tags only from release branch: `v3.2.1`, `v3.2.2`, etc.

### v3.3-dev (feature development)
- Feature branches: `epic/<name>` off `v3.3-dev`
- First commit per epic: tests + docs + gate wiring (tests may initially fail)
- Merge only when epic gates are green locally
- No direct pushes; all changes via feature branch merge

---

## 8. Feature Development Process

1. Create `epic/<name>` branch from `v3.3-dev`
2. First commit: test stubs + docs update + gate wiring in `gate-v33.py` (even if tests fail)
3. Implement features; tests go from red to green
4. Run `gate-v33.py` locally: floor (77/77) + delta gates for this epic must PASS
5. Generate evidence artifacts under `S:\reports\gate-v33\g<N>\`
6. Merge to `v3.3-dev` only when epic gates are green
7. After all epics merged: full gate run, soak, clean-room, bundle, promote

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-14 | M0 scaffold: scope lock created, gate-v33.py scaffolded, version bumped to 3.3.0-dev |
| 2026-02-14 | M0 LOCKED: epics A/B/C defined, G24-G29 specified with binary criteria, risk register + promotion criteria finalized |
| 2026-02-15 | Epic A COMPLETE: G24 (16/16), G25 (14/14), 30 delta tests green, 77 floor intact, 107 combined. Modules: ledger_editor, redaction_engine, provenance_slicer, export_import |
| 2026-02-15 | Epic B COMPLETE: G26 (13/13), G27 (13/13), 26 delta tests green, 107 prior intact, 133 combined. Modules: restore_verifier, triage_recommender, operator_drill |
