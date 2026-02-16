# v3.8 Epic 1: Data Quality & Schema Governance

**Branch:** `v3.8-e1-data-schema`
**Target sections:** J (Data Management), C (Code Quality), D (Configuration Mgmt)
**Projected conservative uplift:** +4 to +6 pts (J: 15->18, C: 16->18, D: 18->19)
**Priority index:** 18 (highest)

---

## Deliverables

### 1. Config/Data Schema Validation Layer

- `services/api-gateway/config_schema.py`: JSON Schema validator for `sonia-config.json`
  - Strict versioned schema (schema_version field)
  - Required keys enforcement
  - Type validation for all config values
  - Unknown key rejection
- `services/api-gateway/data_schema.py`: Schema validation for memory entries
  - Entry type validation (raw, summary, vision_observation, tool_event, etc.)
  - Field completeness checks
  - Provenance field requirements

### 2. Migration Policy Hardening

- `services/memory-engine/migration_policy.py`: Migration governance framework
  - Explicit migration graph validation (topological sort, cycle detection)
  - Rollback strategy: restore-based deterministic rollback policy
  - Migration versioning with forward-only + restore proof
  - Idempotency enforcement (re-run safety)
  - Pre/post migration health checks

### 3. Commit-Hook Quality Checks

- `services/api-gateway/code_quality.py`: Code quality validation module
  - Import ordering validation
  - Docstring presence checks for public functions
  - Complexity threshold enforcement (max cyclomatic complexity)
  - No bare except clauses
  - No print() in production code (must use logger)

---

## Gates

| Gate | Min Checks | Artifact |
|------|------------|----------|
| `schema-validation-gate.py` | 8 | `reports/audit/schema-validation-gate-<ts>.json` |
| `data-migration-gate.py` | 8 | `reports/audit/data-migration-gate-<ts>.json` |

---

## Test Requirements

- Minimum: 20 new unit tests (target: 24-30)
- Test files:
  - `tests/unit/test_config_schema.py` (schema violation, backward compat)
  - `tests/unit/test_data_schema.py` (entry validation, provenance)
  - `tests/unit/test_migration_policy.py` (graph, idempotency, rollback)
  - `tests/unit/test_code_quality.py` (lint checks, complexity)

---

## Acceptance Criteria

1. Both gates PASS (>=8 checks each)
2. >=20 new unit tests PASS
3. All 24 inherited gates remain green
4. Artifacts emitted to `reports/audit/`
5. No modification of existing v3.7 modules

---

## Failure Policy

- If any inherited gate regresses: **HOLD** (fix regression before proceeding)
- If new gates fail: fix and re-run (no merge to v3.8-dev until green)
