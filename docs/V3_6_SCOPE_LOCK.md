# v3.6 Scope Lock

**Branch:** `v3.6-dev`
**Base:** `main` at `77e49b5` (post v3.5 merge)
**Opened:** 2026-02-15
**Promotion criterion:** Same as v3.5 — both standard and conservative passes must independently exceed 78% per-pass floor.

## Candidate Work Items (from remaining gaps)

| Priority | Section | Gap | Suggested Fix |
|----------|---------|-----|---------------|
| P1 | K: Performance | No capacity planning baselines | Document throughput limits per service |
| P2 | R: Dependencies | No license audit / SBOM | Generate SBOM with pip-licenses |
| P3 | S: CI/CD | No CI/CD pipeline | Add GitHub Actions workflow |
| P3 | H: Logging | Trace propagation incomplete | Propagate correlation IDs to all downstream calls |
| P3 | J: Data Mgmt | No migration rollback | Add down-migration support |

## Rules

- No feature commits until scope is locked (this document).
- All changes must pass the 9-gate matrix (`_v35_gate_matrix.py` or successor).
- Hotfixes to v3.5.x go through `release/v3.5.x` branch, not here.
- Promotion requires dual-pass reassessment with same rubric.
