# v4.2 Scope Lock

## Version
4.2.0

## Objective
Three hardening epics that complete the sovereignty, resilience, and reproducibility
guarantees required for Sonia's autonomous operation baseline.

## Locked Scope

1. **E1: Identity/Session/Memory Sovereignty Hardening** -- Strengthen session isolation,
   memory ledger provenance, and token budget enforcement so no external input can
   corrupt Sonia's identity or persistent state.
2. **E2: Chaos Recovery Determinism at Scale** -- Prove that circuit breakers, DLQ replay,
   adapter timeouts, and correlation survival behave identically across repeated chaos
   drills at production-scale concurrency.
3. **E3: Reproducible Release + Cleanroom Parity** -- Guarantee that the release bundle
   can be rebuilt from source with bit-identical gate results, dependency locks, and
   evidence hashes in a cleanroom environment.

## Inherited Baseline
- Gates: 41/41 from v4.1.0 (36 Class A + 3 Class B + 1 Class C + 1 test floor)
- Tests: 753 unit tests
- Dual-pass: 500/500 (both scorers)

## Non-Goals
See V4_2_NON_GOALS.json for machine-checkable list.

## Rules
- Inherited gates are fail-fast HOLD -- no regression allowed
- No feature merge without gate ownership + test budget
- Per-pass floor still required (both scorers >=78%, no section <15)
- All v4.1 governance modules are frozen; extend only
