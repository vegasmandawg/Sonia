# SONIA v4.2.0 Changelog

## Release: v4.2.0-rc1

### Epic 1: Identity/Session/Memory Sovereignty Hardening
- Session namespace isolation invariant enforced
- Memory ledger provenance tracking with full audit chain
- Token budget enforcement prevents state corruption
- Cross-session read/write denial verified

### Epic 2: Chaos Recovery Determinism at Scale
- Circuit breaker state machine deterministic across chaos drills
- DLQ replay produces identical outcomes on repeated runs
- Adapter timeout + correlation survival verified at scale
- Chaos profile registry with versioned hash stability

### Epic 3: Reproducible Release + Cleanroom Parity
- Dependency lock with SHA-256 hashes (79 packages)
- Gate matrix determinism proof (2 identical runs)
- Cleanroom parity gate validates bit-identical builds
- Evidence integrity gate with 5 real filesystem checks

### Infrastructure
- Gate schema v9.0 (40 Class A + 3 Class B + 1 Class C + test floor = 45)
- Dual-pass scorer: 500/500 standard, 500/500 conservative, gap 0
- Inherited baseline: 753 unit tests, 41 gates from v4.1.0
- Total tests: 923+, all passing

### Inherited from v4.1.0
- Governance provenance deepening (E1)
- Fault/recovery determinism under stress (E2)
- Reproducible release + cleanroom parity (E3)
