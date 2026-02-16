# v3.8 Scope Lock

**Opened from:** `main` at v3.7.0 GA
**Date:** 2026-02-15
**Branch:** `v3.8-dev`

---

## Baseline (inherited from v3.7.0)

| Metric | v3.7.0 |
|--------|--------|
| Unit Tests | 299 |
| Gate Matrix | 24/24 |
| New Modules (v3.7) | 6 |
| New Unit Tests (v3.7) | 152 |
| Release Bundle | `S:\releases\v3.7.0\` |
| Manifest SHA-256 | `release-manifest.json` |

---

## v3.7 Dual-Pass Scores (inherited floor)

| Metric | v3.6 Standard | v3.6 Conservative |
|--------|---------------|-------------------|
| **Score** | 489/500 | 441/500 |
| **Percentage** | 97.8% | 88.2% |

> v3.7 did not trigger a reassessment -- its 6 modules and 152 tests strengthen
> sections G, K, L, N without changing the rubric floor.

---

## v3.8 Objectives (2-3 epics max)

Epics to be defined after dual-pass reassessment identifies the highest-value
conservative gaps remaining. Candidate focus areas (pending scorer output):

| Priority | Candidate Area | Sections Affected | Rationale |
|----------|---------------|-------------------|-----------|
| TBD | To be determined by reassessment | -- | -- |

**Epic definitions will be added here once the reassessment is complete.**

---

## Explicit Non-Goals

1. **No CI/CD platform integration** -- single-developer codebase; gate scripts are the CI substitute
2. **No database replication/PITR** -- SQLite with WAL + backup/restore drill is sufficient
3. **No enterprise SSO/RBAC** -- `SONIA_DEV_MODE` auth gate is the auth boundary
4. **No load testing at scale** -- soak scripts with budgeted p95 are the performance boundary
5. **No GDPR right-to-deletion** -- no PII in memory store; redaction gate covers log hygiene
6. **No mypy/pylint/black in CI** -- pre-commit hooks + bandit are the static analysis boundary

These items are acknowledged conservative-scorer deductions that will NOT be addressed
in v3.8. They are structural properties of a single-developer project, not control gaps.

---

## Gate Mapping

### Inherited Baseline (24 gates -- non-negotiable)

| # | Gate Script | Origin | Checks |
|---|------------|--------|--------|
| 1 | auth-posture-gate.py | v3.5 | auth default-on |
| 2 | auth-surface-gate.py | v3.6 | auth surface verification |
| 3 | backup-restore-drill.py | v3.4 | backup RTO drill |
| 4 | cleanroom-parity-gate.py | v3.6 | clean-room parity |
| 5 | consolidated-preaudit.py | v3.4 | 8-check pre-audit |
| 6 | drill-determinism-gate.py | v3.6 | drill determinism |
| 7 | fallback-behavior-gate.py | v3.5 | fallback envelope |
| 8 | incident-bundle-gate.py | v3.4 | incident export |
| 9 | incident-completeness-gate.py | v3.6 | incident completeness |
| 10 | incident-lineage-gate.py | v3.7 | DLQ lineage |
| 11 | memory-silo-gate.py | v3.7 | memory persona silo |
| 12 | output-budget-gate.py | v3.7 | output budget enforcement |
| 13 | perf-budget-gate.py | v3.6 | performance budget |
| 14 | policy-enforcement-gate.py | v3.6 | policy enforcement |
| 15 | rate-limiter-gate.py | v3.4 | rate limiter |
| 16 | recovery-determinism-gate.py | v3.7 | recovery policy determinism |
| 17 | regression-guard-gate.py | v3.6 | regression guard |
| 18 | release-integrity-gate.py | v3.6 | release integrity |
| 19 | restore-integrity-gate.py | v3.6 | restore integrity |
| 20 | runtime-qos-gate.py | v3.7 | runtime QoS SLO |
| 21 | secret-scan-gate.py | v3.4 | secret scan |
| 22 | session-isolation-gate.py | v3.7 | session isolation |
| 23 | traceability-gate.py | v3.4 | control traceability |
| 24 | unit-test-layer-gate.py | v3.5 | unit test layer |

**Fail-fast rule:** If ANY inherited gate fails, v3.8 verdict is HOLD.

### v3.8 Delta Gates (TBD)

Delta gates will be added per-epic as scope is defined. Each epic must add
at least 1 gate with >=6 checks and corresponding unit tests.

---

## Promotion Criteria

| # | Criterion | Required |
|---|-----------|----------|
| 1 | All 24 inherited baseline gates PASS | Yes |
| 2 | All v3.8 delta gates PASS | Yes |
| 3 | All unit tests PASS (>=299 inherited + new) | Yes |
| 4 | Evidence bundle + SHA-256 manifest complete | Yes |
| 5 | Dual-pass reassessment: Standard >= 78% | Yes |
| 6 | Dual-pass reassessment: Conservative >= 78% | Yes |
| 7 | No section below 15/20 on either pass | Yes |

**Verdict:** PROMOTE if all 7 criteria met. HOLD otherwise.

---

## v3.7 Conservative Gaps Remaining

Pending dual-pass reassessment with locked audit contract.

---

## Rules

1. Additive only -- no modification of v3.7 modules without regression proof
2. All new modules must have unit tests + gate scripts
3. Feature branches merge to v3.8-dev via --no-ff
4. Baseline 24 gates must remain green at all times
5. Scorer contract locked at stage start (see `docs/SCORER_CONTRACT.md`)
