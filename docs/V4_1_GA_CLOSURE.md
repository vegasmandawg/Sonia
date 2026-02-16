# v4.1.0 GA Closure Report

## Release Identity
| Field | Value |
|-------|-------|
| Version | 4.1.0 |
| GA Tag | `v4.1.0` |
| RC Tag | `v4.1.0-rc1` |
| Commit | `e6da1fa` (main merge), `3753211` (RC) |
| Date | 2026-02-16 |
| Bundle | `S:\releases\v4.1.0\` |
| Schema | v8.0 |

## Objective
No-regression + deeper determinism. Building on v4.0.0 (500/500) with
governance provenance, chaos recovery determinism, and reproducible release
parity guarantees.

## Epic Summary

### E1: Governance Provenance Deepening
- **Modules:** provenance_registry.py, lineage_mapper.py, evidence_integrity.py, provenance_reporter.py
- **Gate:** 10/10 PASS
- **Tests:** 36 unit tests
- **Branch:** v4.1-e1-provenance → merged at `62b1379`

### E2: Fault/Recovery Determinism Under Stress
- **Modules:** chaos_policy.py, restore_policy.py, replay_policy.py, incident_lineage.py, determinism_report.py
- **Gate:** 10/10 PASS
- **Tests:** 49 unit tests
- **Branch:** v4.1-e2-chaos-recovery → merged at `0e70a42`

### E3: Reproducible Release + Cleanroom Parity
- **Modules:** repro_build_policy.py, cleanroom_parity.py, release_manifest_policy.py, rollback_determinism.py, release_lineage.py
- **Gate:** 10/10 PASS
- **Tests:** 46 unit tests
- **Branch:** v4.1-e3-repro-release → merged at `3753211`

## Gate Matrix
| Class | Count | Status |
|-------|-------|--------|
| A (inherited) | 36 | PASS |
| B (delta) | 3 | PASS |
| C (evidence) | 1 | PASS |
| Floor | 1 | PASS |
| **Total** | **41** | **PROMOTE** |

## Test Suite
| Metric | Value |
|--------|-------|
| Total tests | 753 |
| Inherited | 622 |
| E1 new | 36 |
| E2 new | 49 |
| E3 new | 46 |
| Failures | 0 |
| GA threshold | 712 |

## Dual-Pass Reassessment
| Scorer | Score | Floor | Status |
|--------|-------|-------|--------|
| Standard | 500/500 | >= 495 | PASS |
| Conservative | 500/500 | >= 495 | PASS |

- **Inter-pass gap:** 0 (threshold: <= 6)
- **Min section (conservative):** 20 (threshold: >= 15)
- **Closed-deduction protection:** ACTIVE (all epics passed)

## Evidence Set
13 frozen artifacts in `S:\reports\audit\v4.1-evidence-frozen\`:
- gate-matrix-preflight.json
- unit-summary-preflight.json
- epic1-provenance-gate.json
- epic2-chaos-recovery-gate.json
- epic3-repro-gate.json
- dualpass-standard.json / dualpass-conservative.json / dualpass-diff.json
- dualpass-summary.md
- FINAL_SCORECARD.json / FINAL_SCORECARD.md
- SCOPE_LOCK.md / SCORER_CONTRACT.md

All artifacts SHA-256 hashed in evidence-manifest.json.

## Bundle Contents
22 files in `S:\releases\v4.1.0\`:
- gate-report.json (41/41 PROMOTE)
- release-manifest.json + .sha256
- requirements-frozen.txt (45 packages)
- dependency-lock.json (SHA-256 per package)
- changelog.md
- FINAL_SCORECARD.json / .md
- env-snapshot.json
- evidence/ (15 files with integrity manifest)

## Branch Choreography
| Branch | Action | Base |
|--------|--------|------|
| v4.1-dev | merged to main | — |
| main | received merge | v4.1-dev |
| v4.1.0-rc1 | tag at `3753211` | v4.1-dev |
| v4.1.0 | tag at `e6da1fa` | main |
| release/v4.1.x | created | v4.1.0 |
| v4.2-dev | created | v4.1.0 |

## Inherited Baseline
- v4.0.0: 37/37 gates, 622 tests, 500/500 dual-pass
- v3.9.0: System closure, model routing, EVA supervision, hybrid memory
- v3.0.0: API contract, perception bridge, typed memory ledger
- v2.8.0: Deterministic operations
- v2.5.0: Action pipeline, reliability hardening, observability

## Phase D Closure Steps
1. ✅ Preflight + floor revalidation: 41/41 PROMOTE, 753/753
2. ✅ Dual-pass reassessment: 500/500 both, gap=0
3. ✅ Freeze immutable evidence set: 13 artifacts
4. ✅ Tag RC: v4.1.0-rc1 at 3753211
5. ✅ Build GA release bundle: 22 files
6. ✅ Bundle hash manifests + validation: 8/8 checks PASS
7. ✅ GA merge, tag, branch choreography: main, v4.1.0, release/v4.1.x, v4.2-dev
8. ✅ Publish closure snapshot: this document

## Post-Close Protocol
- Release stamp: v4.1.0 at e6da1fa on main
- Evidence frozen: SHA-256 manifest verified
- Dual-pass: 500/500 both scorers
- Bundle: 22 files, all hashes verified
- Branches: release/v4.1.x and v4.2-dev created
