# SONIA v3.3.0 GA Evidence Index

**Release Date**: 2026-02-15
**Tags**: `v3.3.0-rc1`, `v3.3.0` at commit `f9e0321` (RC/GA), merge to main at `5a65f45`
**Contract**: `v3.0.0` (unchanged)
**Branch Topology**: `main` (GA), `release/v3.3.x` (hotfix), `v3.4-dev` (next)

---

## 1. Gate Results (G18-G29)

| Gate | Suite | Tests | Result |
|------|-------|-------|--------|
| G18 | Voice latency budget | 4 | PASS |
| G19 | Barge-in replay determinism | 20 | PASS |
| G20 | Perception dedupe correctness | 15 | PASS |
| G21 | Confirmation storm integrity | 8 | PASS |
| G22 | Memory proposal governance | 16 | PASS |
| G23 | Memory replay integrity | 14 | PASS |
| G24 | Ledger edit governance (Epic A) | 16 | PASS |
| G25 | Redaction + provenance slicing (Epic A) | 14 | PASS |
| G26 | Restore integrity (Epic B) | 13 | PASS |
| G27 | Incident triage automation (Epic B) | 13 | PASS |
| G28 | Privacy boundary enforcement (Epic C) | 14 | PASS |
| G29 | Zero-frame + confirmation hardening (Epic C) | 10 | PASS |

**Totals**: 14/14 gates PASS, 157 tests (77 floor + 80 delta), 0 failures

---

## 2. Soak Summary

12 invariants tested, ALL ZERO:

| # | Invariant | Value |
|---|-----------|-------|
| 1 | silent_write_count | 0 |
| 2 | false_bypass_count | 0 |
| 3 | replay_divergence_count | 0 |
| 4 | voice_cancel_violations | 0 |
| 5 | illegal_transition_attempts | 0 |
| 6 | double_decision_attempts | 0 |
| 7 | conflict_unsurfaced_count | 0 |
| 8 | direct_edit_bypass_count | 0 |
| 9 | redaction_leak_count | 0 |
| 10 | restore_state_mismatch_count | 0 |
| 11 | privacy_bypass_count | 0 |
| 12 | zero_frame_violation_count | 0 |

**Verdict**: PASS

---

## 3. Artifact Manifest

| Artifact | Path | Verification |
|----------|------|-------------|
| GA release bundle | `S:\releases\v3.3.0\` | `python scripts/release/verify-hashes-v33.py` |
| RC1 release bundle | `S:\releases\v3.3.0-rc1\` | `python scripts/release/verify-hashes-v33.py --dir S:\releases\v3.3.0-rc1` |
| Gate report | `S:\reports\gate-v33\gate-report.json` | SHA-256 in release manifest |
| Soak report | `S:\reports\gate-v33\soak-report.json` | SHA-256 in release manifest |
| G24-G29 evidence | `S:\reports\gate-v33\g24\` through `g29\` | Per-gate evidence-manifest.json |
| Epic gate reports | `S:\reports\gate-v33\epic-{a,b,c}-gate-report.json` | Individual epic verdicts |
| Scope lock | `S:\docs\V3_3_SCOPE_LOCK.md` | Canonical contract |

---

## 4. Epic Merge Commits

| Epic | Name | Branch | Merge Commit | Delta Tests |
|------|------|--------|-------------|-------------|
| A | Memory Ledger Operations v2 | `epic/memory-ledger-v2` | `3351a1c` (tests), merged via `--no-ff` | 30 |
| B | Recovery + Incident Tooling | `epic/recovery-incident-tooling` | `0786cf8` (impl), merged at `44fdca1` | 26 |
| C | Perception Privacy Hardening | `epic/perception-privacy-hardening` | `a715019` (impl), merged at `c647bd7` | 24 |

---

## 5. Modules Delivered

### Epic A: Memory Ledger Operations v2
- `services/memory_ops/ledger_editor.py` -- edit/merge with provenance
- `services/memory_ops/redaction_engine.py` -- deterministic redaction
- `services/memory_ops/provenance_slicer.py` -- "why retrieved?" chains
- `services/memory_ops/export_import.py` -- ledger export/import with integrity

### Epic B: Recovery + Incident Tooling
- `services/eva-os/restore_verifier.py` -- post-restore invariant checks
- `services/eva-os/triage_recommender.py` -- automated triage from snapshots
- `services/eva-os/operator_drill.py` -- reproducible drill framework

### Epic C: Perception Privacy Hardening
- `services/perception/privacy_gate.py` -- privacy state machine + PII scrubbing
- `services/perception/zero_frame_enforcer.py` -- generation-based zero-frame guarantee

---

## 6. Known Limitations / Non-Goals Carried to v3.4

- **No contract bump**: SONIA_CONTRACT remains at v3.0.0
- **No live service integration testing**: all tests are unit/integration against module APIs
- **Privacy gate PII patterns**: current set covers SSN, email, phone, CC -- additional patterns deferred
- **Operator drill real-mode execution**: drills run dry_run=True only; real-mode deferred
- **Memory export/import**: file-based only; no network transport
- **Perception pipeline end-to-end soak**: soak validates invariants via simulation, not live perception stream
- **No UI changes**: all v3.3 deliverables are backend/service-layer only

---

## 7. Release Branch Policy

- `release/v3.3.x`: hotfix and security patches only (see `docs/HOTFIX_INTAKE_V33.md`)
- `v3.4-dev`: next feature development branch
- Cherry-picks from main to release branch require traceability: `(cherry-picked from <sha>)`
- Patch tags: `v3.3.1`, `v3.3.2`, etc. from release branch only
