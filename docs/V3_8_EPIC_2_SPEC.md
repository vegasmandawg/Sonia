# v3.8 Epic 2: Automation & Observability Hardening

**Branch:** `v3.8-e2-auto-observability`
**Target sections:** S (CI/CD & Automation), K (Performance), N (Observability), L (Testing)
**Projected conservative uplift:** +3 to +4 pts (S: 18->19, K/N/L: 19->20)
**Priority index:** 10

---

## Deliverables

### 1. Automation Coverage Hardening

- `services/api-gateway/automation_coverage.py`: Gate coverage analyzer
  - Enumerate all gate scripts in `scripts/gates/`
  - Map gates to audit sections (A-Y)
  - Detect section coverage gaps (sections with no gate)
  - Verify all gates produce JSON artifacts
  - Deterministic local runner completeness proof (no CI platform required)

### 2. Trace Propagation Hardening

- `services/api-gateway/trace_propagation.py`: Correlation ID continuity verifier
  - Verify correlation_id flows through turn pipeline stages
  - Assert correlation_id in all log entries for a given request
  - Cross-service boundary correlation (gateway -> router -> memory)
  - Detect orphaned requests (no correlation_id)
  - Trace completeness score per request

### 3. Performance Evidence Hardening

- `services/api-gateway/perf_profile.py`: Sustained load profile generator
  - Steady-state QoS budget conformance check
  - p50/p95/p99 calculation over sliding windows
  - SLO violation counter with threshold alerting
  - Profile artifact generation for audit evidence

### 4. Test Coverage Metrics

- `services/api-gateway/test_coverage.py`: Test coverage analyzer
  - Enumerate all source modules in `services/api-gateway/`
  - Map modules to test files in `tests/unit/`
  - Compute coverage ratio (modules with tests / total modules)
  - Identify untested modules
  - Coverage trend tracking

---

## Gates

| Gate | Min Checks | Artifact |
|------|------------|----------|
| `automation-coverage-gate.py` | 8 | `reports/audit/automation-coverage-gate-<ts>.json` |
| `trace-propagation-gate.py` | 8 | `reports/audit/trace-propagation-gate-<ts>.json` |

---

## Test Requirements

- Minimum: 20 new unit tests (target: 22-28)
- Test files:
  - `tests/unit/test_automation_coverage.py` (gap detection, mapping)
  - `tests/unit/test_trace_propagation.py` (correlation flow, orphan detection)
  - `tests/unit/test_perf_profile.py` (window stats, SLO checks)
  - `tests/unit/test_test_coverage.py` (module mapping, ratio calc)

---

## Acceptance Criteria

1. Both gates PASS (>=8 checks each)
2. >=20 new unit tests PASS
3. All 24 inherited gates remain green
4. Artifacts emitted to `reports/audit/`
5. Sustained-load profile artifact: `reports/audit/perf-steady-state-<ts>.json`
6. No modification of existing v3.7 modules

---

## Failure Policy

- If any inherited gate regresses: **HOLD** (fix regression before proceeding)
- If new gates fail: fix and re-run (no merge to v3.8-dev until green)
