# v3.9 Scope Lock

**Branch:** `v3.9-dev`
**Base:** `main` at v3.8.0 GA (015eb68)
**Created:** 2026-02-16

---

## Inherited Floor

All 28 gates from v3.8.0 are inherited as non-negotiable baseline:
- 24 v3.7 inherited gates
- 4 v3.8 delta gates (schema-validation, data-migration, automation-coverage, trace-propagation)

### Score Floor

| Scorer | Floor |
|--------|-------|
| Standard | 493/500 (98.6%) |
| Conservative | 479/500 (95.8%) |

No section may regress below its v3.8.0 score.

---

## Objectives

Close the 14-point conservative gap identified at v3.8.0 GA (Standard 493, Conservative 479, Variance 14).

Two epics, ranked by priority_index:

1. **Epic 1: Conservative Gap Closure (High-Variance Sections)** -- +8 pts projected
2. **Epic 2: Remaining Deduction Elimination** -- +6 pts projected

Target: Conservative 493/500, Variance 0.

---

## Non-Goals

- No new service creation
- No external dependency additions without security review
- No architectural changes to service topology
- No breaking changes to existing API contracts

---

## Promotion Criteria

1. All inherited gates (28) remain green
2. All delta gates pass
3. Standard >= 493/500
4. Conservative >= 479/500
5. No section below 15
6. Variance <= 50
7. Release bundle with SHA-256 manifest

---

## Epics

### Epic 1: Conservative Gap Closure (High-Variance Sections)

| Field | Value |
|-------|-------|
| Branch | `v3.9-e1-conservative-gaps` |
| Sections | J (-2), S (-2), M (-1), O (-1), Q (-1), W (-1) |
| Projected Uplift | +8 conservative points |
| Priority Index | 32 |
| Min Tests | 20 |
| Target Tests | 30 |

**Modules:** schema_evolution.py, data_integrity_checks.py, gate_section_mapper.py, durability_policy.py, operational_readiness.py, privacy_controls.py

**Gates (predefined):**
- `coverage-completeness-gate.py` (>=8 checks)
- `data-durability-gate.py` (>=8 checks)

### Epic 2: Remaining Deduction Elimination

| Field | Value |
|-------|-------|
| Branch | `v3.9-e2-deduction-sweep` |
| Sections | C (-1), D (-1), K (-1), L (-1), N (-1), T (-1) |
| Projected Uplift | +6 conservative points |
| Priority Index | 24 |
| Min Tests | 20 |
| Target Tests | 26 |

**Modules:** lint_config.py, config_audit.py, slo_dashboard.py, test_strategy.py, health_check_registry.py, doc_completeness.py

**Gates (predefined):**
- `deduction-sweep-gate.py` (>=10 checks)
- `test-strategy-gate.py` (>=8 checks)

---

## Gate Ownership

| Gate | Owner | Status |
|------|-------|--------|
| 24 v3.7 inherited (gates/) | Inherited from v3.7.0 | LOCKED |
| 4 v3.8 delta (release/) | Inherited from v3.8.0 | LOCKED |
| coverage-completeness-gate.py | Epic 1 | PREDEFINED |
| data-durability-gate.py | Epic 1 | PREDEFINED |
| deduction-sweep-gate.py | Epic 2 | PREDEFINED |
| test-strategy-gate.py | Epic 2 | PREDEFINED |

---

## Release Discipline

- `release/v3.8.x` -- hotfix and security patches only. No feature backports.
- `v3.9-dev` -- all feature work. Epic branches merge `--no-ff` back to `v3.9-dev`.
- `main` -- receives `v3.9-dev` only at GA via `--no-ff` merge after full promotion gate.
- Tags: `v3.9.0-rc1` at validation commit, `v3.9.0` at GA merge to main.
