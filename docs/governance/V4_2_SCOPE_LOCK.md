# v4.2 Scope Lock

## Version
4.2.0-dev

## Objective
TBD — epics not yet defined. This document locks the governance framework
and inherited baseline; epic scope will be added when E1-E3 are defined.

## Locked Scope
Three epics (to be defined):

1. **E1: TBD** — placeholder
2. **E2: TBD** — placeholder
3. **E3: TBD** — placeholder

## Inherited Baseline
- Gates: 41/41 from v4.1.0 (36 Class A + 3 Class B + 1 Class C + 1 test floor)
- Tests: 753 unit tests
- Dual-pass: 500/500 (both scorers)

## Non-Goals
See V4_2_NON_GOALS.json for machine-checkable list.

## Rules
- Inherited gates are fail-fast HOLD — no regression allowed
- No feature merge without gate ownership + test budget
- Per-pass floor still required (both scorers >=78%, no section <15)
- All v4.1 governance modules are frozen; extend only
