# Changelog: v3.8.0

**Release date:** 2026-02-16
**Previous version:** v3.7.0
**Branch:** v3.8-dev

## Summary

v3.8.0 closes two remediation epics targeting audit sections J, C, D (data quality) and S, K, N, L (automation/observability). Eight new modules, 131 new tests, and four delta gates were added with zero regressions to the inherited 24-gate baseline.

## Epic 1: Data Quality & Schema Governance

**Sections:** J (Data Integrity), C (Configuration), D (Dependency Management)

### New modules
- `services/api-gateway/config_schema.py` -- ConfigSchemaValidator with 14 field specs, type/range/allowed-value validation
- `services/api-gateway/data_schema.py` -- DataSchemaValidator for 7 memory entry types with provenance enforcement
- `services/memory-engine/migration_policy.py` -- MigrationPolicyEngine with topological sort, cycle detection, idempotency guards
- `services/api-gateway/code_quality.py` -- AST-based CodeQualityChecker (bare_except, print, docstring, complexity, import ordering)

### New tests (74)
- test_config_schema.py (17), test_data_schema.py (18), test_migration_policy.py (21), test_code_quality.py (18)

### New gates (2)
- schema-validation-gate.py (10/10 checks)
- data-migration-gate.py (10/10 checks)

## Epic 2: Automation & Observability Hardening

**Sections:** S (CI/CD & Automation), K (Performance), N (Observability), L (Testing)

### New modules
- `services/api-gateway/automation_coverage.py` -- Gate coverage analyzer with section mapping and gap detection
- `services/api-gateway/trace_propagation.py` -- Correlation ID verifier for 6-stage pipeline with orphan detection
- `services/api-gateway/perf_profile.py` -- Sustained load profiler with sliding window stats and SLO budget checking
- `services/api-gateway/test_coverage.py` -- Test coverage analyzer with module-to-test mapping and trend tracking

### New tests (57)
- test_automation_coverage.py (12), test_trace_propagation.py (15), test_perf_profile.py (19), test_test_coverage.py (12)

### New gates (2)
- automation-coverage-gate.py (10/10 checks)
- trace-propagation-gate.py (10/10 checks)

## M0 Infrastructure

- gate-v38.py gate runner with retry logic and failure classification
- dualpass-reassess-v38.py dual-pass scorer with evidence inventory
- Scorer contract (SCORER_CONTRACT.md)
- Scope lock (V3_8_SCOPE_LOCK.md)

## Scores

| Scorer | Score | Pct |
|--------|-------|-----|
| Standard | 493/500 | 98.6% |
| Conservative | 479/500 | 95.8% |

## Gate Matrix

28/28 gates PASS (24 inherited + 4 delta)

## Test Totals

430 unit tests, 0 failures, 131 new in v3.8
