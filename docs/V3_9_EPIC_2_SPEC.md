# v3.9 Epic 2: Remaining Deduction Elimination

**Branch:** `v3.9-e2-deduction-sweep`
**Target sections:** C (-1), D (-1), K (-1), L (-1), N (-1), T (-1)
**Projected conservative uplift:** +6 pts (487 -> 493)
**Priority index:** 4*0 + 2*6 + 2*6 = 24

---

## Rationale

After Epic 1 closes the -2 deductions, six sections remain with -1 each on conservative. Eliminating all of them brings conservative to parity with standard (493/500) and reduces variance to 0.

---

## Deliverables

### 1. Code Quality Evidence (C: -1 -> 0)

- `services/api-gateway/lint_config.py`: Lint rule registry with severity levels, suppression tracking

### 2. Configuration Completeness (D: -1 -> 0)

- `services/api-gateway/config_audit.py`: Config key inventory, default documentation, drift detection

### 3. Performance Evidence (K: -1 -> 0)

- `services/api-gateway/slo_dashboard.py`: SLO budget aggregator with per-capability p50/p95/p99 reporting

### 4. Test Strategy Evidence (L: -1 -> 0)

- `services/api-gateway/test_strategy.py`: Test pyramid validator (unit/integration/e2e ratio), gap finder

### 5. Observability Completeness (N: -1 -> 0)

- `services/api-gateway/health_check_registry.py`: Health check inventory, endpoint verification, staleness detection

### 6. Documentation Quality (T: -1 -> 0)

- `services/api-gateway/doc_completeness.py`: Doc coverage analyzer (README, API docs, changelog presence)

---

## Gates (predefined)

| Gate | Min Checks | Location | Artifact |
|------|------------|----------|----------|
| `deduction-sweep-gate.py` | 10 | scripts/release/ | `reports/audit/deduction-sweep-gate-<ts>.json` |
| `test-strategy-gate.py` | 8 | scripts/release/ | `reports/audit/test-strategy-gate-<ts>.json` |

---

## Test Requirements (predefined)

- Minimum: 20 new unit tests (target: 24-30)
- Test files:
  - `tests/unit/test_lint_config.py` (rule registry, suppression)
  - `tests/unit/test_config_audit.py` (inventory, drift)
  - `tests/unit/test_slo_dashboard.py` (aggregation, reporting)
  - `tests/unit/test_test_strategy.py` (pyramid validation, gaps)
  - `tests/unit/test_health_check_registry.py` (inventory, staleness)
  - `tests/unit/test_doc_completeness.py` (coverage analysis)

---

## Acceptance Criteria

1. Both gates PASS (>=8 checks each)
2. >=20 new unit tests PASS
3. All 28 inherited gates remain green
4. Conservative deductions for C, D, K, L, N, T eliminated
5. Standard/conservative variance reduced to <= 5 pts
6. No modification of existing modules (additive only)
