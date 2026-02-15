# v3.3 Scope Lock

**Status**: M0 — Planning & Baseline Hardening
**Branch**: `v3.3-dev`
**Base**: v3.2.0 GA (`07879ed`)
**Contract**: SONIA_CONTRACT pinned at `v3.0.0` (no breaking changes planned)

---

## 1. Objectives

Epics TBD — to be locked before first feature commit.

| Epic | Name | Gates | Status |
|------|------|-------|--------|
| A | TBD | G24/G25 | not started |
| B | TBD | G26/G27 | not started |
| C | TBD | G28/G29 | not started |

## 2. Non-Goals

- No breaking changes to SONIA_CONTRACT v3.0.0
- No modifications to v3.2 modules unless bugfix (those go to release/v3.2.x)
- No new external dependencies without explicit justification
- No changes to core service boot sequence or port assignments

## 3. Contract Policy

`SONIA_CONTRACT` remains pinned at `v3.0.0`. If any epic requires a contract bump,
it must be called out as a separate scope item with migration path documented before
approval.

## 4. Gate Map

### Inherited Floor (v3.2, mandatory — must remain green)

| Gate | Suite | Tests | Origin |
|------|-------|-------|--------|
| G18 | test_latency_budget_g18.py | 4 | v3.2 Epic A |
| G19 | test_bargein_cancel_semantics.py + test_replay_determinism.py + test_turn_lifecycle.py | 20 | v3.2 Epic A |
| G20 | test_dedupe_correctness.py + test_priority_routing.py | 15 | v3.2 Epic B |
| G21 | test_confirmation_storm_integrity.py | 8 | v3.2 Epic B |
| G22 | test_proposal_governance.py | 16 | v3.2 Epic C |
| G23 | test_replay_determinism.py (memory_ops) | 14 | v3.2 Epic C |

**Inherited floor total: 77 tests**

### New Gates (v3.3 delta — TBD)

| Gate | Epic | Suite | Tests | Status |
|------|------|-------|-------|--------|
| G24 | A | TBD | TBD | not wired |
| G25 | A | TBD | TBD | not wired |
| G26 | B | TBD | TBD | not wired |
| G27 | B | TBD | TBD | not wired |
| G28 | C | TBD | TBD | not wired |
| G29 | C | TBD | TBD | not wired |

## 5. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Floor regression from new feature code | Medium | High | gate-v33.py runs full v3.2 floor before delta gates |
| R2 | Module path drift (voice, perception, memory_ops) | Low | Medium | conftest.py explicit imports, no implicit sys.path |
| R3 | Soak invariant inflation (too many zeros to track) | Low | Medium | Keep soak invariants additive-only, never remove |
| R4 | Contract bump pressure from new epics | Medium | High | Contract pinned; bump requires separate approval |
| R5 | Branch contamination of release/v3.2.x | Low | High | Only bugfix/security branches merge to release branch |

## 6. Promotion Criteria (binary — all must be true)

- [ ] All inherited gates (G18-G23) PASS (77/77)
- [ ] All new gates (G24-G29) PASS
- [ ] Combined floor >= 77 + delta tests
- [ ] Cross-epic soak: all invariants ZERO
- [ ] Clean-room reproducibility from tagged RC
- [ ] Release bundle assembled with SHA-256 manifest
- [ ] No SONIA_CONTRACT bump unless explicitly approved

## 7. Release Branch Policy (release/v3.2.x)

- Only `bugfix/*` and `security/*` branches may merge into `release/v3.2.x`
- Require PR + CI gate + at least one reviewer
- Cherry-pick only from `main`/`v3.3-dev` with traceability: `(cherry-picked from <sha>)`
- Patch tags only from release branch: `v3.2.1`, `v3.2.2`, etc.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-14 | M0 scaffold: scope lock created, gate-v33.py scaffolded, version bumped to 3.3.0-dev |
