# Changelog: SONIA v3.9.0

**Release Date:** 2026-02-16
**Previous Version:** v3.8.0

---

## Summary

v3.9.0 closes the 14-point conservative scorer gap identified at v3.8.0 GA,
achieving zero variance between Standard and Conservative dual-pass scores.

- **Standard:** 496/500 (99.2%)
- **Conservative:** 496/500 (99.2%)
- **Variance:** 0 points (target was 0, down from 14)
- **Gates:** 33 total (28 inherited + 4 delta + 1 test floor)
- **Unit Tests:** 523 (430 inherited + 93 new)

---

## Epic 1: Conservative Gap Closure (+8 conservative points)

Closed conservative deductions in sections J, S, M, O, Q, W.

### New Modules
- `services/memory-engine/durability_policy.py` -- Migration monotonicity checker,
  backup chain verifier, retention consistency checker, connection durability checker
- `services/api-gateway/coverage_completeness.py` -- Machine-checkable A-Y section
  mapping to gates, tests, and artifacts with completeness analysis

### New Gates
- `scripts/gates/data-durability-gate.py` (10 checks)
- `scripts/gates/coverage-completeness-gate.py` (10 checks)

### New Tests (56)
- `tests/unit/test_data_durability.py` (25 tests)
- `tests/unit/test_coverage_completeness.py` (15 tests)
- `tests/unit/test_epic1_section_closure.py` (16 tests)

---

## Epic 2: Deduction Elimination (+6 conservative points)

Closed conservative deductions in sections C, D, K, L, N, T.

### New Modules
- `services/api-gateway/lint_config.py` -- Lint severity policy with 7 default rules
- `services/api-gateway/config_audit.py` -- Config drift detection with SHA-256 hashing
- `services/api-gateway/slo_dashboard.py` -- SLO budget tracking with MET/BREACHED evaluation
- `services/api-gateway/contract_trace.py` -- Contract consistency and trace propagation checks
- `services/api-gateway/observability_requirements.py` -- Telemetry field completeness policy
- `services/api-gateway/test_strategy_policy.py` -- Test strategy reporting and coverage analysis

### New Gates
- `scripts/gates/deduction-sweep-gate.py` (10 checks)
- `scripts/gates/test-strategy-gate.py` (10 checks)

### New Tests (37)
- `tests/unit/test_deduction_sweep.py` (24 tests)
- `tests/unit/test_test_strategy_gate.py` (13 tests)

---

## Infrastructure

- Gate runner `gate-v39.py` with `always_retry` for transient inherited gate failures
- Dual-pass reassessment: `dualpass-reassess-v39.py` (filesystem-scan) + `dual-pass-v39.py` (artifact-driven)
- Scorer contract locked at M0: `docs/SCORER_CONTRACT_V39.md`
- Scope lock: `docs/V3_9_SCOPE_LOCK.md`

---

## Non-Goals (unchanged from v3.8)

- CI/CD platform integration
- Database replication/PITR
- Enterprise SSO/RBAC
- Load testing at scale
- GDPR right-to-deletion
- mypy/pylint/black in CI
