# Scorer Contract v4.2

## Version
4.2.0-dev

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
- Gate matrix v9 (45 gates: 41 inherited + 4 delta)
- Per-epic gate reports (E1, E2, E3)
- Unit test summary (>= 843 tests, 0 failures)
- Release manifest with SHA-256 checksums
- Scope lock and non-goals documents

## Inherited Evidence
All v4.1 evidence carries forward:
- v4.1 epic gates (E1 provenance, E2 chaos recovery, E3 reproducible release)
- v4.0 epic gates (E1 session, E2 recovery, E3 runtime)
- v3.9 epic gates (coverage, durability, deduction sweep, test strategy)
- All 41 inherited gates from v4.1

## Determinism Contract
- Zero deterministic failures tolerated
- Chaos recovery tests must pass
- Replay determinism must be verified
- Restore invariants must hold at scale
- All v4.1 determinism guarantees carry forward

## Immutability
This contract is locked at v4.2 M0. Changes require new version tag.
