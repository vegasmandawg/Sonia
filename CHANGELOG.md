# Changelog

All notable changes to Sonia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-02-15

**Stabilization Baseline** -- hardening-only release on top of v3.0.0.

### Added
- H1 hardening test suite: replay determinism (9), recovery integrity (15), confirmation load (15) -- 39 new tests
- 5 chaos fault-injection scripts: service unavailable, malformed envelope, confirmation storm, provenance corruption, session overload
- Promotion gate expanded from 12 to 17 gates (5 hardening gates)
- Contractual invariant checks: MAX_PENDING=50 and DEFAULT_TTL=120.0 derived from source
- Release assembly scripts: RC1 bundler, GA bundler, hash verifier
- Gate specification document (V3_1_GATE_SPEC.md)
- Hardening plan document (V3_1_H1_HARDENING_PLAN.md)

### Changed
- SONIA_VERSION bumped to 3.1.0 (from 3.0.0)
- Gate hygiene rules updated to tolerate hardening working directories
- M1 contract test accepts v3.0.0, v3.1.0, and v3.1.0-dev versions

### Unchanged (no contract drift)
- SONIA_CONTRACT remains v3.0.0
- All v3.0.0 API surfaces, message schemas, and contract tests unchanged
- 112 baseline regression tests still pass unmodified

### Evidence
- Promotion gate: 17/17 PASS
- Regression: 151 tests PASS (112 baseline + 39 hardening)
- Chaos: 5/5 scripts PASS, 0 bypass attempts
- Cleanroom rebuild: verified from v3.1.0-rc1 tag
- Rollback drill: v3.0.0 validated (112 passed)
- Artifact hashes: 16/16 matched
- Release bundle: `S:\releases\v3.1.0\`

## [3.0.0] - 2026-02-14

**API Contract + Perception Bridge** -- first contract-versioned release.

### Added
- M1: SONIA_CONTRACT v3.0.0, sonia-config.json canonical, /v1/config endpoint
- M2: Identity model (companion, operator, session), auth middleware, RBAC
- M3: Typed memory ledger (5 types), token budget, retention policy, search filters
- M4: PerceptionMemoryBridge (scene to typed memory + provenance), non-bypass gate

### Evidence
- Promotion gate: 12/12 PASS
- Regression: 112 tests PASS (18 M1 + 28 M2 + 38 M3 + 28 M4)
- Release bundle: `S:\releases\v3.0.0\`

## [2.9.0] - 2026-02-09

**System Closure** -- model routing, EVA supervision, hybrid memory.

### Added
- Model Router: Anthropic + OpenRouter (httpx), routing policy (local_only/cloud_allowed/provider_pinned)
- EVA-OS: ServiceSupervisor with /healthz probes, state machine (5 states), dependency graph
- Memory Engine: HybridSearchLayer (BM25 + LIKE), ProvenanceTracker, token budget
- Hygiene: lifespan migration (6 services), shared/version.py, dedup requirements

### Evidence
- 68 new tests + 24 post-close drills; 12/12 gates green

## [2.8.0] - 2026-02-09

**Deterministic Operations** -- cancellation, budget, bypass-proof gate, operator UX.

### Added
- Model call cancellation context
- Memory recall budget enforcement
- Perception action gate (bypass-proof confirmation state machine)
- Operator session state machine

### Evidence
- 156 new tests; 565 total; 14-gate promotion; 700-op soak

## [2.6.0] - 2026-02-09

**Companion Experience Layer** -- persona, vision presence, embodiment UI.

### Added

#### Track A: Persona + Fine-tune Pipeline
- Dataset directory contract with manifests
- Dataset manifest schema v1.1.0: strict key validation, deterministic build IDs
- 5-stage text processing pipeline: normalize, dedupe, classify, split, export
- Identity invariant enforcement: 3 severity levels, 13 anchor rules
- Evaluation harness: 5-dimension checks, baseline comparison
- Unified CLI: validate-manifest, process-text, enforce-invariants, export-jsonl, run-eval

#### Track B: Vision Presence
- Vision capture service (port 7060): privacy hard gate, zero-frame invariant, ring buffer
- Perception pipeline (port 7070): event bus, SceneAnalysis, fail-closed privacy

#### Track C: Embodiment UI
- Electron + React + Three.js avatar application
- Zustand 5-state FSM, ACK model, ConnectionManager with backoff
- DiagnosticsPanel, StatusIndicator, ControlBar

#### Cross-Track
- Unified event envelope (20 types, correlation IDs, validate_envelope)
- 17 cross-track integration tests

### Evidence
- 16-gate promotion checklist; rollback to v2.5 validated

## [2.5.0] - 2026-02-08

**Foundation through Reliability** -- stages 0-7 cumulative.

### Added
- Core microservices (6 services), EVA-OS supervisor
- Turn pipeline, voice sessions, tool safety gate
- Multimodal (vision + voice), memory quality controls
- Action pipeline with desktop adapters and circuit breakers
- Reliability hardening, retry taxonomy, DLQ replay
- Observability, chaos recovery, backup/restore

### Evidence
- 189 integration tests; 12-gate promotion

## [1.0.0] - 2026-02-08

**Initial Release** -- full architecture, all core services, documentation.

### Added
- EVA-OS deterministic supervisor with risk-aware approval gating
- 5 core microservices: api-gateway, model-router, memory-engine, pipecat, openclaw
- Canonical JSON envelope system for inter-service communication
- 13 tools across 4 risk tiers
- Configuration management (sonia-config.json)
- Operational infrastructure (startup, diagnostics, logging)
- Complete documentation suite

---

[3.1.0]: https://github.com/vegasmandawg/sonia/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/vegasmandawg/sonia/compare/v2.9.0...v3.0.0
[2.9.0]: https://github.com/vegasmandawg/sonia/compare/v2.8.0...v2.9.0
[2.8.0]: https://github.com/vegasmandawg/sonia/compare/v2.6.0...v2.8.0
[2.6.0]: https://github.com/vegasmandawg/sonia/compare/v2.5.0...v2.6.0
[2.5.0]: https://github.com/vegasmandawg/sonia/compare/v1.0.0...v2.5.0
[1.0.0]: https://github.com/vegasmandawg/sonia/releases/tag/v1.0.0

---

**Project Created**: 2026-02-08
**Latest GA**: v3.1.0 (2026-02-15)
