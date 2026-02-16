# SONIA v4.1.0 — Final Summary

**Released:** 2026-02-16 | **Tag:** `v4.1.0` | **Bundle:** `S:\releases\v4.1.0\`

## What Changed
Three governance epics deepening determinism guarantees on top of v4.0.0:

1. **Provenance** — immutable policy provenance, control lineage mapping, evidence integrity validation
2. **Chaos Recovery** — bounded chaos scenarios, restore pre/postconditions, DLQ replay semantics, incident lineage chains
3. **Reproducible Release** — frozen dependency sets, cleanroom parity checking, release manifest completeness, rollback determinism

## By the Numbers
- **41/41** gates PROMOTE (36 inherited + 3 delta + 1 evidence + 1 floor)
- **753** unit tests, 0 failures (622 inherited + 131 new)
- **500/500** dual-pass (Standard and Conservative), gap = 0
- **30/30** epic gate checks (E1: 10, E2: 10, E3: 10)
- **15** governance modules added
- **13** frozen evidence artifacts with SHA-256 manifest

## What's Next
- `release/v4.1.x` branch for patch releases
- `v4.2-dev` branch open for next development cycle
