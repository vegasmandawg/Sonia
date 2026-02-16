# v4.1 Scope Lock

## Version
4.1.0-dev

## Objective
No-regression + deeper determinism. Not score chasing (v4.0 achieved 500/500).

## Locked Scope
Three epics focused on provenance, chaos recovery, and reproducible release:

1. **E1: Governance Provenance Deepening** — policy provenance, control lineage, immutable evidence joins
2. **E2: Fault/Recovery Determinism Under Stress** — chaos cases, replay determinism, restore invariants at scale
3. **E3: Reproducible Release + Cleanroom Parity** — deterministic rebuild parity, release artifact verification, rollback drills

## Inherited Baseline
- Gates: 37/37 from v4.0.0 (32 Class A + 3 Class B + 1 Class C + 1 test floor)
- Tests: 622 unit tests
- Dual-pass: 500/500 (both scorers)

## Non-Goals
See V4_1_NON_GOALS.json for machine-checkable list.

## Rules
- Inherited gates are fail-fast HOLD — no regression allowed
- No feature merge without gate ownership + test budget
- Per-pass floor still required (both scorers >=78%, no section <15)
- All v4.0 governance modules (session, recovery, runtime) are frozen; extend only
