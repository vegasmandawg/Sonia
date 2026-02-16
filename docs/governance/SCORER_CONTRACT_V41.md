# Scorer Contract v4.1

## Version
4.1.0-dev

## Scoring Model
- 25 sections (A..Y), 0-20 per section, total 500
- Standard scorer: 2 points per missing required check, 1 per missing bonus
- Conservative scorer: 3 points per missing required check, 1 per missing bonus
- Closed-deduction protection when all epic gates pass

## Floors
- Both scorers must achieve >= 495/500
- No section below 15 on conservative pass
- Inter-pass gap <= 6 points

## Evidence Sources
- Gate matrix v8 (41 gates: 37 inherited + 3 delta + 1 evidence)
- Per-epic gate reports (E1, E2, E3)
- Unit test summary (>= 712 tests, 0 failures)
- Release manifest with SHA-256 checksums
- Scope lock and non-goals documents

## Inherited Evidence
All v4.0 evidence carries forward:
- v4.0 epic gates (E1 session, E2 recovery, E3 runtime)
- v3.9 epic gates (coverage completeness, data durability, deduction sweep, test strategy)
- All 37 inherited gates from v4.0

## Determinism Contract
- Zero deterministic failures tolerated
- Chaos recovery tests must pass
- Replay determinism must be verified
- Restore invariants must hold at scale

## Immutability
This contract is locked at v4.1 M0. Changes require new version tag.
