# v3.7 Scope Lock

**Opened:** 2026-02-16
**Branch:** `v3.7-dev`
**Base:** `main` at merge commit `60f50a8` (v3.6.0 GA)
**Prior version:** v3.6.0 (Standard 489/500, Conservative 441/500)

---

## Baseline

| Metric | Value |
|--------|-------|
| Standard score | 489/500 (97.8%) |
| Conservative score | 441/500 (88.2%) |
| Mean | 465/500 (93.0%) |
| Gates | 17/17 PASS |
| Unit tests | 147/147 PASS |
| Release tag | `v3.6.0` |

## Remaining Conservative Gaps (from v3.6 deductions)

| Priority | Section | Gap | Conservative Deduction |
|----------|---------|-----|----------------------|
| P1 | M | SQLite without replication/PITR | -5 |
| P1 | C | No mypy/pylint/black in CI gates | -4 |
| P1 | J | No database migration tooling | -4 |
| P2 | S | No CI/CD platform integration | -3 |
| P2 | Q | No GDPR right-to-deletion | -3 |
| P2 | K | No load testing at scale | -3 |
| P3 | Various | Minor gaps (no WAF, no canary, no link checking) | ~-15 |

**Conservative ceiling if all P1+P2 resolved:** ~463/500 (92.6%)

## Rules

1. No feature work until scope lock is approved
2. All changes must reference a section from the gap table above
3. Gate matrix must remain green (17/17 minimum)
4. Unit test count must not decrease (147 minimum)
5. Dual-pass scoring required before promotion
