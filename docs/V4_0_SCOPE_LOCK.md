# v4.0 Scope Lock

**Branch:** `v4.0-dev`
**Base:** `main` at v3.9.0 GA (eef3818)
**Created:** 2026-02-16

---

## Inherited Floor

All 33 gates from v3.9.0 are inherited as non-negotiable baseline:
- 24 v3.7 inherited gates
- 4 v3.8 delta gates
- 4 v3.9 delta gates (coverage-completeness, data-durability, deduction-sweep, test-strategy)
- 1 unit test floor (523 tests)

### Score Floor

| Scorer | Floor |
|--------|-------|
| Standard | 496/500 (99.2%) |
| Conservative | 496/500 (99.2%) |

No section may regress below its v3.9.0 score.

---

## Objectives

TBD -- scope to be defined after v4.0 planning session.

---

## Non-Goals

Inherited from v3.9.0:
- CI/CD platform integration
- Database replication/PITR
- Enterprise SSO/RBAC
- Load testing at scale
- GDPR right-to-deletion
- mypy/pylint/black in CI

---

## Test Budgets

| Epic | Minimum Tests | Target | Floor Enforced |
|------|--------------|--------|----------------|
| Epic 1 (TBD) | 20 | 30 | Yes |
| Epic 2 (TBD) | 20 | 30 | Yes |
| Epic 3 (TBD) | 20 | 30 | Yes |
| Evidence Integrity | 10 | 15 | Yes |
| **Inherited** | **523** | **523** | **Yes** |

No feature merge is permitted without gate ownership and test targets.

---

## Promotion Criteria

1. All inherited gates (33) remain green
2. All delta gates pass
3. Standard >= 496/500
4. Conservative >= 496/500
5. No section below 15
6. Variance <= 50
7. Release bundle with SHA-256 manifest
8. Per-epic test budget met (>= minimum)
9. Per-pass floor mandatory (both scorers must meet threshold)

---

## Gate Architecture (schema v7.0)

| Class | Count | Description |
|-------|-------|-------------|
| A | 33 + 1 test floor | Inherited baseline (fail-fast, always_retry) |
| B | 3 (placeholder) | Epic delta gates (per-epic ownership) |
| C | 1 (placeholder) | Cross-cutting (evidence integrity) |

Gate runner: `scripts/release/gate-v40.py`

---

## Machine-Checkable Contracts

- `docs/governance/V4_0_EPIC_MAP.json` -- epic definitions, test budgets, rules
- `docs/governance/V4_0_PROMOTION_CRITERIA.json` -- promotion criteria with thresholds
- `docs/governance/V4_0_NON_GOALS.json` -- inherited non-goals with review policy
