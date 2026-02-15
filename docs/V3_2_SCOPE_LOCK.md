# V3.2 Scope Lock

**Branch**: `v3.2-dev`
**Base**: `v3.1.0` (stabilization baseline)
**Contract posture**: v3.0.0 contract frozen; new surface behind feature flags.
**Created**: 2026-02-15

## Design Principle

v3.2 is the first feature release on top of the v3.1 stability baseline.
All new surface area ships behind feature flags. The v3.0.0 contract is
immutable -- breaking it requires a v4.0 scope decision.

## Candidate Epics (pick 2-3 for first milestone)

### Epic A: Companion Session Experience
Voice latency optimization, barge-in handling, turn-taking improvements.
- Target: sub-200ms p99 round-trip for voice interactions
- Scope: pipecat service, stream.py WebSocket handler, session manager
- Feature flag: `SONIA_FF_VOICE_V2`

### Epic B: Perception-to-Action Ergonomics
Confirmation batching, priority lanes, action coalescing.
- Target: reduce confirmation fatigue by 60%+ for routine operations
- Scope: perception_action_gate.py, tool_policy.py, confirmation queue
- Feature flag: `SONIA_FF_CONFIRM_BATCH`

### Epic C: Memory Ledger Operator Tooling
Review/edit/redact interface, budget visibility, retention dashboard.
- Target: operator can audit and manage memory without API calls
- Scope: memory-engine API, new operator routes, UI components
- Feature flag: `SONIA_FF_MEMORY_OPS`

## Entry Criteria (all must be true before first feature commit)

- [x] `v3.2-dev` branch off `v3.1.0` tag
- [x] SONIA_VERSION = `3.2.0-dev`
- [x] This scope lock document written
- [x] `gate-v32.py` scaffolded (v3.1 gates as stability floor)
- [ ] Epic selection committed (update checkboxes below)

## Selected Epics

> **Decision pending** -- select 2-3 epics and update this section before
> writing any feature code.

- [ ] Epic A
- [ ] Epic B
- [ ] Epic C

## Exit Criteria

- All v3.1 regression tests pass (151 baseline)
- New feature tests pass behind flags
- Feature flags documented in config schema
- Gate-v32 promotion: all gates PASS
- No contract drift (SONIA_CONTRACT still v3.0.0)

## Sprint Cadence

1. **Week 1-2**: Design docs for selected epics, interface contracts
2. **Week 3-6**: Implementation with continuous integration
3. **Week 7**: Hardening, chaos expansion, soak
4. **Week 8**: RC freeze, cleanroom, GA promote
