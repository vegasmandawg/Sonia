# v3.8 Scope Lock

**Opened from:** `main` at v3.7.0 GA
**Date:** 2026-02-15

## Baseline

| Metric | v3.7.0 |
|--------|--------|
| Unit Tests | 299 |
| Gate Matrix | 24/24 |
| New Modules (v3.7) | 6 |
| New Unit Tests (v3.7) | 152 |

## v3.7 Conservative Gaps Remaining

Pending dual-pass reassessment with locked audit contract.

## Rules

1. Additive only — no modification of v3.7 modules without regression proof
2. All new modules must have unit tests + gate scripts
3. Feature branches merge to v3.8-dev via --no-ff
4. Baseline 24 gates must remain green at all times
