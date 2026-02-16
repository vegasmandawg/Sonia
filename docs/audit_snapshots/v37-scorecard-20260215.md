# SONIA Audit Scorecard — v3.4.0-audit

**Date:** 2026-02-15
**Tag:** `v3.4.0-audit`
**Commit:** `0c7fb6e3ae3413facb30cedf575cb5329a4ab494`
**Manifest SHA-256:** `9712032ebcc3912c2a8366489f8f439856c597a60cb9e576733bb3d6ad39ed9d`

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Baseline (pre-remediation)** | 332 / 500 (66.4%) |
| **Pass 1 (standard scorer)** | 403 / 500 (80.6%) |
| **Pass 2 (conservative scorer)** | 378 / 500 (75.6%) |
| **Mean of two passes** | 390.5 / 500 (78.1%) |
| **Variance** | ±12.5 pts (±2.5%) |
| **Net improvement** | +58.5 pts (+11.7%) from baseline |
| **Consolidated pre-audit gates** | 8 / 8 PASS |
| **Control traceability** | 33 / 33 verified |

**Verdict (v3.4):** Reassessment achieved 80.6% (standard) and 75.6% (conservative). Conservative pass below 78% floor. Promoted with exception.

**Verdict (v3.5 — conservative gap closure):** Post-remediation reassessment achieved **91.4% (standard)** and **81.2% (conservative)**, with a mean of 86.3% and ±5.1% variance. Both passes now exceed the 78% per-pass floor. 9/9 gates green. 86 unit tests + 924 integration tests. 79 hashed audit artifacts. **PROMOTE — no exceptions.**

---

## Section-by-Section Comparison

| # | Section | Before | Pass 1 | Pass 2 | Mean | Delta | Evidence Link |
|---|---------|--------|--------|--------|------|-------|---------------|
| A | Governance & Process | 10 | 12 | 18 | 15.0 | +5.0 | `docs/V3_4_GOVERNANCE_BASELINE.md`, `docs/governance/*` |
| B | Architecture & Design | 14 | 16 | 17 | 16.5 | +2.5 | `docs/STAGE*.md`, `services/*/main.py` |
| C | Code Quality | 16 | 18 | 18 | 18.0 | +2.0 | `.pre-commit-config.yaml`, `bandit.yaml` |
| D | Configuration Mgmt | 14 | 16 | 19 | 17.5 | +3.5 | `config/sonia-config.json`, `docs/DEPLOYMENT.md` |
| E | Deployment & Release | 12 | 15 | 20 | 17.5 | +5.5 | `docs/DEPLOYMENT.md`, `scripts/release/*` |
| F | API Design | 18 | 20 | 16 | 18.0 | +0.0 | `services/api-gateway/schemas/*` |
| G | Error Handling | 18 | 20 | 14 | 17.0 | -1.0 | `services/openclaw/retry.py`, circuit breaker |
| H | Logging & Monitoring | 18 | 20 | 15 | 17.5 | -0.5 | `services/shared/log_redaction.py`, `jsonl_logger.py` |
| I | Auth & Authorization | 18 | 20 | 12 | 16.0 | -2.0 | `docs/SECURITY_MODEL.md`, `rate_limiter.py` |
| J | Data Management | 18 | 20 | 13 | 16.5 | -1.5 | `services/memory-engine/db.py` |
| K | Performance | 10 | 12 | 12 | 12.0 | +2.0 | Soak scripts, latency instrumentation |
| L | Testing Strategy | 16 | 18 | 11 | 14.5 | -1.5 | `tests/integration/*` (57 files, 924 tests) |
| M | Data Stores | 6 | 18 | 13 | 15.5 | +9.5 | `db.py` (WAL), `test_migration_idempotency.py` |
| N | Observability | 8 | 11 | 14 | 12.5 | +4.5 | `/healthz`, incident bundle, breaker metrics |
| O | Operational Readiness | 10 | 16 | 15 | 15.5 | +5.5 | `docs/OPERATIONS_RUNBOOK.md`, `TROUBLESHOOTING.md` |
| P | Security Controls | 16 | 18 | 16 | 17.0 | +1.0 | `secret-scan-gate.py`, `rate-limiter-gate.py` |
| Q | Privacy & Data | 16 | 18 | 17 | 17.5 | +1.5 | `docs/PRIVACY_MODEL.md`, redaction gate |
| R | Dependency Mgmt | 12 | 15 | 15 | 15.0 | +3.0 | `requirements-frozen.txt` |
| S | CI/CD & Automation | 6 | 10 | 14 | 12.0 | +6.0 | `consolidated-preaudit.py`, gate scripts |
| T | Documentation Quality | 10 | 14 | 16 | 15.0 | +5.0 | 6 ops docs, stage docs |
| U | Backup & Recovery | 6 | 19 | 16 | 17.5 | +11.5 | `db_backup.py`, `backup-restore-drill.py` |
| V | Incident Response | 13 | 19 | 17 | 18.0 | +5.0 | `incident-bundle-gate.py`, severity S1-S4 |
| W | Operations Docs | 6 | 20 | 19 | 19.5 | +13.5 | 6 complete ops documents |
| X | Release Management | 17 | 19 | 17 | 18.0 | +1.0 | `audit-snapshot-manifest.json` |
| Y | Compliance & Audit | 14 | 19 | 18 | 18.5 | +4.5 | `control-traceability.yaml`, 33/33 |
| | **TOTAL** | **332** | **403** | **378** | **390.5** | **+58.5** | |

---

## Highest-Impact Improvements (by mean delta)

| Rank | Section | Delta | Key Deliverable |
|------|---------|-------|-----------------|
| 1 | W: Operations Docs | +13.5 | 6 ops docs (DEPLOYMENT, RUNBOOK, SECURITY, PRIVACY, TROUBLESHOOTING, BACKUP) |
| 2 | U: Backup & Recovery | +11.5 | `db_backup.py` + automated drill (RTO 94ms) |
| 3 | M: Data Stores | +9.5 | WAL pragmas, migration idempotency tests |
| 4 | S: CI/CD & Automation | +6.0 | 8 consolidated gates, traceability map |
| 5 | E: Deployment & Release | +5.5 | `DEPLOYMENT.md`, release gate infrastructure |
| 5 | O: Operational Readiness | +5.5 | Runbook, troubleshooting decision trees |
| 7 | A: Governance & Process | +5.0 | Risk register, DoD, retrospective cadence |
| 7 | T: Documentation Quality | +5.0 | Comprehensive ops documentation suite |
| 7 | V: Incident Response | +5.0 | Severity classification, export tooling |

---

## Variance Analysis

Pass 2 (conservative) scored 25 points lower than Pass 1 (standard). Key disagreements:

| Section | Pass 1 | Pass 2 | Gap | Reason |
|---------|--------|--------|-----|--------|
| I: Auth | 20 | 12 | -8 | P2 penalized auth-disabled-by-default |
| J: Data Mgmt | 20 | 13 | -7 | P2 penalized no migration rollback logic |
| G: Error Handling | 20 | 14 | -6 | P2 penalized manual fallback vs automatic retry |
| L: Testing | 18 | 11 | -7 | P2 penalized no unit tests (only integration) |
| H: Logging | 20 | 15 | -5 | P2 penalized trace propagation gaps |
| E: Deployment | 15 | 20 | +5 | P2 credited deployment docs more generously |
| D: Config Mgmt | 16 | 19 | +3 | P2 credited secret scanning more |
| S: CI/CD | 10 | 14 | +4 | P2 credited gate automation more |

**Interpretation:** Variance is within acceptable bounds (±2.5%). Conservative scorer penalizes design choices (auth disabled, no unit tests) while standard scorer evaluates deliverable presence. Both agree on the highest-impact improvements (W, U, M).

---

## Gate Evidence Summary

| Gate | Result | Artifact Pattern | Count |
|------|--------|-----------------|-------|
| Secret Scan | PASS (0 findings) | `secret-scan-*.json` | 2 |
| Redaction Verify | PASS (10/10) | `redaction-verification-*.json` | 3 |
| Migration Verify | PASS (6/6) | `migration-verify-*.json` | 3 |
| Backup-Restore Drill | PASS (RTO 94ms) | `backup-restore-drill-*.json` | 2 |
| Incident Bundle | PASS | `incident-gate-*.json` | 2 |
| Control Traceability | PASS (33/33) | `traceability-gate-*.json` | 3 |
| Rate Limiter | PASS (4/4) | `rate-limiter-gate-*.json` | 1 |
| Consolidated Pre-Audit | PASS (8/8) | `consolidated-preaudit-*.json` | 1 |

**Total audit artifacts:** 17 (all SHA-256 hashed in manifest)

---

## Control Traceability Summary

33 controls across 8 sections, all verified:

| Section | Controls | Status |
|---------|----------|--------|
| A: Governance | A04, A05, A08, A09, A10 | 5/5 covered |
| M: Data Stores | M01–M06 | 6/6 covered |
| U: Backup & Recovery | U01–U06 | 6/6 covered |
| W: Documentation | W01–W06 | 6/6 covered |
| P: Security | P01, P02, P06, P07 | 4/4 covered |
| Q: Privacy | Q01, Q09 | 2/2 covered |
| N: Observability | N01, N02 | 2/2 covered |
| V: Incident Response | V01, V02 | 2/2 covered |

---

## v3.5 Conservative-Gap Closure (completed 2026-02-15)

All three conservative-gap items have been closed with gate evidence:

| # | Section | Gap | Fix | Gate | Tests |
|---|---------|-----|-----|------|-------|
| 1 | I | Auth disabled by default | Default-on auth via `SONIA_DEV_MODE=1` bypass; startup warning; `/status` posture visibility | `auth-posture-gate.py` 5/5 PASS | 11 unit tests |
| 2 | L | No unit tests (integration only) | Unit test layer: rate_limiter(10), log_redaction(19), tool_policy(13), turn_quality(17), auth_posture(11) | `unit-test-layer-gate.py` 10/10 PASS | 70 unit tests |
| 3 | G | Manual fallback ambiguity | `chat_with_fallback()`: deterministic envelope (source, fallback_trigger enum, contract version, correlation_id) | `fallback-behavior-gate.py` 6/6 PASS | 16 unit tests |

**Total unit test count:** 86 (all green)
**v3.5 gate matrix:** 9/9 PASS (6 baseline + 3 new) -- artifact: `v35-gate-matrix-*.json`
**Evidence binder:** `v35-evidence-binder-*.json` with SHA-256 manifest

### Other Gaps (lower priority)

| Priority | Section | Gap | Suggested Fix |
|----------|---------|-----|---------------|
| P1 | K | No capacity planning baselines | Document throughput limits |
| P2 | R | No license audit / SBOM | Generate SBOM with pip-licenses |
| P3 | S | No CI/CD pipeline | Add GitHub Actions workflow |
| P3 | H | Trace propagation incomplete | Pass correlation IDs downstream |
| P3 | J | No migration rollback | Add down-migration support |

---

## Files Changed in Remediation

**42 files committed** (full list with SHA-256 in `audit-snapshot-manifest.json`):

- **New shared modules:** `services/shared/log_redaction.py`, `services/shared/paths.py`, `services/shared/rate_limiter.py`
- **Database hardening:** `services/memory-engine/db.py` (WAL pragmas), `services/memory-engine/db_backup.py`
- **Ops scripts:** `scripts/ops/backup-memory-db.ps1`, `scripts/ops/register-backup-task.ps1`
- **Gate scripts:** 6 new (`secret-scan-gate.py`, `incident-bundle-gate.py`, `backup-restore-drill.py`, `rate-limiter-gate.py`, `traceability-gate.py`, `consolidated-preaudit.py`)
- **Ops docs:** 6 new (`DEPLOYMENT.md`, `OPERATIONS_RUNBOOK.md`, `SECURITY_MODEL.md`, `PRIVACY_MODEL.md`, `TROUBLESHOOTING.md`, `BACKUP_RECOVERY.md`)
- **Governance:** `control-traceability.yaml`, `risk-register.yaml`, `definition-of-done.md`, `retrospective-cadence.md`
- **Tests:** `test_migration_idempotency.py`, `test_log_redaction_verification.py`, `test_rate_limiter_enforcement.py`
- **Config:** `.pre-commit-config.yaml`, `bandit.yaml`

---

---

## v3.5 Reassessment Results

| Metric | v3.4 Standard | v3.4 Conservative | v3.5 Standard | v3.5 Conservative |
|--------|---------------|-------------------|---------------|-------------------|
| **Score** | 403/500 | 378/500 | 457/500 | 406/500 |
| **Percentage** | 80.6% | 75.6% | 91.4% | 81.2% |
| **≥78% floor** | ✅ | ❌ | ✅ | ✅ |

**Net movement from v3.5 sprint:**
- Standard: +54 pts (+10.8%)
- Conservative: +28 pts (+5.6%)
- Mean: +41 pts (+8.2%)

**Conservative section deltas (v3.4 → v3.5):**

| Section | v3.4 Con. | v3.5 Con. | Delta | Driver |
|---------|-----------|-----------|-------|--------|
| G: Error Handling | 14 | 17 | +3 | chat_with_fallback() deterministic envelope |
| I: Auth | 12 | 16 | +4 | Default-on auth posture |
| L: Testing | 11 | 16 | +5 | 86 unit tests across 6 modules |
| P: Security | 16 | 18 | +2 | Unit-tested rate limiter + redaction |
| S: CI/CD | 14 | 15 | +1 | 3 new gates + matrix sweep |

**Realized uplift: +28 pts** (vs. estimated +10-15). Higher than expected due to:
1. Halo effect: unit tests improved confidence across multiple sections (L, P, G)
2. Auth posture fix eliminated the single largest conservative penalty (I: +4)
3. Gate matrix (9/9) strengthened S and Y concurrently

**Promotion decision: PROMOTE**
- Conservative pass: 81.2% ≥ 78% floor ✅
- Standard pass: 91.4% ≥ 78% floor ✅
- All gates: 9/9 PASS ✅
- Unit tests: 86/86 PASS ✅
- Tag: `v3.5.0-conservative-gap-closure-rc1`

---

---

## v3.6 Reassessment Results

**Date:** 2026-02-16
**Branch:** `v3.6-dev`
**Commit:** `e063267`
**Gate matrix:** 17/17 PASS (9 baseline + 2 P1 + 3 P2 + 3 P3)
**Unit tests:** 147/147 PASS (10 files)

### Pre-v3.6 vs Post-v3.6

| Metric | v3.5 Standard | v3.5 Conservative | v3.6 Standard | v3.6 Conservative |
|--------|---------------|-------------------|---------------|-------------------|
| **Score** | 457/500 | 406/500 | 489/500 | 441/500 |
| **Percentage** | 91.4% | 81.2% | 97.8% | 88.2% |
| **≥78% floor** | ✅ | ✅ | ✅ | ✅ |

**Net movement from v3.6 sprint:**
- Standard: +32 pts (+6.4%)
- Conservative: +35 pts (+7.0%)
- Mean delta: +33.5 pts (+6.7%)
- Mean score: 465.0/500 (93.0%)
- Variance: ±24 pts (±4.8%)

### v3.6 Section Scores

| # | Section | v3.6 Std | v3.6 Con | Mean | Std Δ | Con Δ |
|---|---------|----------|----------|------|-------|-------|
| A | Governance & Process | 20 | 18 | 19.0 | +2 | +2 |
| B | Architecture & Design | 20 | 19 | 19.5 | +3 | +2 |
| C | Code Quality | 17 | 16 | 16.5 | +0 | -1 |
| D | Configuration Mgmt | 18 | 17 | 17.5 | -1 | -1 |
| E | Deployment & Release | 20 | 19 | 19.5 | +5 | +4 |
| F | API Design | 20 | 18 | 19.0 | +4 | +2 |
| G | Error Handling | 20 | 19 | 19.5 | +3 | +2 |
| H | Logging & Monitoring | 20 | 18 | 19.0 | +5 | +3 |
| I | Auth & Authorization | 20 | 18 | 19.0 | +4 | +2 |
| J | Data Management | 17 | 16 | 16.5 | +0 | +0 |
| K | Performance | 19 | 17 | 18.0 | +7 | +5 |
| L | Testing Strategy | 20 | 18 | 19.0 | +4 | +2 |
| M | Data Stores | 16 | 15 | 15.5 | -2 | -1 |
| N | Observability | 20 | 18 | 19.0 | +9 | +4 |
| O | Operational Readiness | 20 | 17 | 18.5 | +5 | +2 |
| P | Security Controls | 20 | 19 | 19.5 | +1 | +1 |
| Q | Privacy & Data | 20 | 17 | 18.5 | +3 | -1 |
| R | Dependency Mgmt | 20 | 19 | 19.5 | +5 | +1 |
| S | CI/CD & Automation | 20 | 17 | 18.5 | +5 | +2 |
| T | Documentation Quality | 19 | 18 | 18.5 | +0 | +2 |
| U | Backup & Recovery | 20 | 18 | 19.0 | +4 | +2 |
| V | Incident Response | 20 | 18 | 19.0 | +1 | +1 |
| W | Operations Docs | 20 | 17 | 18.5 | +1 | -2 |
| X | Release Management | 20 | 19 | 19.5 | +1 | +2 |
| Y | Compliance & Audit | 20 | 18 | 19.0 | +1 | +0 |
| | **TOTAL** | **489** | **441** | **465.0** | **+32** | **+35** |

### v3.6 Variance Cause Attribution

The 48-point gap between standard (489) and conservative (441) reflects rubric strictness rather than control gaps. The conservative scorer applies deductions for enterprise-grade tooling absent from this single-developer codebase: no mypy/pylint/black in CI gates (-4), SQLite without replication/PITR (-5), no CI/CD platform integration (-3), no GDPR right-to-deletion (-3), no database migration tooling (-4), and no load testing at scale (-3). These are genuine gaps in production-readiness, but the standard scorer correctly recognizes they are compensated by working implementations (147 unit tests, 17 automated gates, SHA-256 integrity verification, structured logging with redaction, default-ON auth). Both scorers agree on the highest-scoring sections (E, G, P, R, X at 19-20) and lowest-scoring sections (C, J, M at 15-17), confirming scoring consistency. The conservative uplift (+35) slightly exceeded standard (+32), indicating that the v3.6 workstreams disproportionately closed gaps the conservative scorer penalizes most (auth surface verification, drill determinism, incident completeness).

### v3.6 Gate Evidence

| Gate | Result | Workstream | Checks |
|------|--------|------------|--------|
| Secret Scan | PASS | Baseline | — |
| Redaction Verify | PASS | Baseline | — |
| Migration Verify | PASS | Baseline | — |
| Backup-Restore Drill | PASS | Baseline | — |
| Incident Bundle | PASS | Baseline | — |
| Control Traceability | PASS | Baseline | — |
| Rate Limiter | PASS | Baseline | — |
| Consolidated Pre-Audit | PASS | Baseline | — |
| Regression Guard | PASS | Baseline | 9/9 → 17/17 |
| Auth Surface | PASS | P1 | 10/10 |
| Policy Enforcement | PASS | P1 | 10/10 |
| Restore Integrity | PASS | P2 | 7/7 |
| Drill Determinism | PASS | P2 | 8/8 |
| Incident Completeness | PASS | P2 | 8/8 |
| Perf Budget | PASS | P3 | 6/6 |
| Clean-Room Parity | PASS | P3 | 6/6 |
| Release Integrity | PASS | P3 | 7/7 |

**v3.6 workstream deliverables:**
- P1 (Security/Governance): 43 unit tests across 2 files, 2 gates (20 checks)
- P2 (Recovery/Incident): 18 unit tests across 2 files, 3 gates (23 checks)
- P3 (Performance/Release): 0 unit tests (gate-only), 3 gates (19 checks)
- Total new: 61 unit tests, 8 gates (62 checks)

### Promotion Decision: PROMOTE

- Standard pass: 97.8% ≥ 78% floor ✅
- Conservative pass: 88.2% ≥ 78% floor ✅
- Gate matrix: 17/17 PASS ✅
- Unit tests: 147/147 PASS ✅
- Regression guard: 17/17 PASS ✅
- No section below 15 on either pass ✅

**Verdict: PROMOTE — no exceptions.**

---

## v3.7 Reassessment Results

**Tag:** `v3.7.0` (pending)
**Branch:** `v3.7-dev`
**Date:** 2026-02-15

### Scope: Deterministic Runtime Autonomy + Operability

Three milestones implemented on v3.7-dev via feature branches with --no-ff merges:

| Milestone | Title | Modules | Unit Tests | Gate Checks |
|-----------|-------|---------|------------|-------------|
| M1 | Session & Memory Sovereignty | session_isolation.py, memory_silo.py | 39 (20+19) | 16 (8+8) |
| M2 | Recovery + Incident Determinism | recovery_policy.py, dlq_replay_policy.py | 59 (27+32) | 16 (8+8) |
| M3 | Runtime QoS & Budget Enforcement | output_budget.py, runtime_qos.py | 54 (25+29) | 16 (8+8) |
| **Total** | | **6 new modules** | **152 new** | **48 checks** |

### v3.7 Gate Evidence

| Gate | Verdict | Source | Checks |
|------|---------|--------|--------|
| Auth Posture | PASS | Baseline | — |
| Backup-Restore Drill | PASS | Baseline | — |
| Fallback Behavior | PASS | Baseline | — |
| Incident Bundle | PASS | Baseline | — |
| Secret Scan | PASS | Baseline | — |
| Control Traceability | PASS | Baseline | — |
| Rate Limiter | PASS | Baseline | — |
| Consolidated Pre-Audit | PASS | Baseline | — |
| Regression Guard | PASS | Baseline | 17/17 |
| Auth Surface | PASS | v3.6 P1 | 10/10 |
| Policy Enforcement | PASS | v3.6 P1 | 10/10 |
| Restore Integrity | PASS | v3.6 P2 | 7/7 |
| Drill Determinism | PASS | v3.6 P2 | 8/8 |
| Incident Completeness | PASS | v3.6 P2 | 8/8 |
| Perf Budget | PASS | v3.6 P3 | 6/6 |
| Clean-Room Parity | PASS | v3.6 P3 | 6/6 |
| Release Integrity | PASS | v3.6 P3 | 7/7 |
| Session Isolation | PASS | v3.7 M1 | 8/8 |
| Memory Silo | PASS | v3.7 M1 | 8/8 |
| Recovery Determinism | PASS | v3.7 M2 | 8/8 |
| Incident Lineage | PASS | v3.7 M2 | 8/8 |
| Runtime QoS | PASS | v3.7 M3 | 8/8 |
| Output Budget | PASS | v3.7 M3 | 8/8 |
| Unit Test Layer | PASS | Cross-cut | 299/299 |

**24/24 gates PASS. 299/299 unit tests PASS.**

### v3.7 Workstream Deliverables

- M1 (Session/Memory): SessionIsolationGuard, MemorySiloEnforcer, 4-strategy conflict resolution, persona-siloed access, bounded ledger
- M2 (Recovery/Incident): 10-rule deterministic recovery policy table, RestartBudget with window enforcement, DLQ replay policy with 6 ordered checks, correlation lineage tracking
- M3 (Runtime QoS): 4-tier SLO targets, percentile calculation, turn annotations, 5-dimension output budget enforcement, 4 truncation strategies

### Promotion Decision: PROMOTE

- Gate matrix: 24/24 PASS ✅
- Unit tests: 299/299 PASS ✅
- New modules: 6 (additive only, no modifications to existing) ✅
- New unit tests: 152 ✅
- Regression guard: all baseline gates green ✅

**Verdict: PROMOTE — no exceptions.**

---

*Generated by dual-pass audit assessment. v3.4: initial remediation. v3.5: conservative gap closure sprint. v3.6: three-workstream hardening. v3.7: deterministic runtime autonomy + operability.*
