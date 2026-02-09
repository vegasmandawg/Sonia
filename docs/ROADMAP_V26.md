# v2.6 Roadmap

**Baseline**: v2.5.0 (ac64fbbb)
**Branch**: `next` or `v2.6-dev`
**Philosophy**: Deterministic, measurable, reversible acceptance gates.

---

## Scope Areas

### 1. Multi-Node / Failover Orchestration
**Goal**: Service continuity across node failures.

| Milestone | Deliverable | Acceptance Gate |
|-----------|-------------|-----------------|
| 2.6-m1 | Service registry with heartbeat protocol | Registry tracks 2+ nodes; failover within 5s |
| 2.6-m2 | Leader election for stateful services (memory-engine, DLQ) | Split-brain test passes; no data loss on leader swap |
| 2.6-m3 | Cross-node action pipeline routing | Action completes when primary node goes down mid-execution |
| 2.6-m4 | Orchestrator integration (port 8000) | Orchestrator drives multi-node topology; health supervisor aggregates |

### 2. Predictive SLO Breach Detection
**Goal**: Pre-fault alerting from latency/error trends.

| Milestone | Deliverable | Acceptance Gate |
|-----------|-------------|-----------------|
| 2.6-m5 | Latency time-series collection (sliding window per capability) | p50/p95/p99 computed over configurable windows |
| 2.6-m6 | Trend detector (linear regression on p95 over last N minutes) | Alert fires when projected p95 exceeds SLO budget within 10 minutes |
| 2.6-m7 | Error rate budget tracker (per-capability, per-hour) | Budget exhaustion triggers advisory before breaker trips |
| 2.6-m8 | Operator notification channel (webhook or log alert) | Alert delivered within 30s of detection |

### 3. Policy-as-Code Hardening
**Goal**: Side-effect authorization paths are declarative and auditable.

| Milestone | Deliverable | Acceptance Gate |
|-----------|-------------|-----------------|
| 2.6-m9 | Policy DSL for tool authorization rules | Existing 4-tier policy expressible in DSL; round-trip test passes |
| 2.6-m10 | Policy version control (policy files tracked in git) | Policy changes require promotion gate; policy hash in baseline contract |
| 2.6-m11 | Runtime policy hot-reload without service restart | Policy update reflected within 5s; no request drops during reload |
| 2.6-m12 | Policy audit trail (who changed what, when) | Every policy mutation logged with correlation ID |

### 4. Operator UX Improvements
**Goal**: Single-pane incident timeline + replay provenance explorer.

| Milestone | Deliverable | Acceptance Gate |
|-----------|-------------|-----------------|
| 2.6-m13 | Incident timeline API (chronological event stream) | Single GET returns ordered events for any time window |
| 2.6-m14 | Replay provenance: trace any DLQ entry back to originating turn | Provenance chain verified for 100% of test DLQ entries |
| 2.6-m15 | Correlation graph: given a correlation_id, return full causal chain | Graph includes memory recall, model call, tool exec, DLQ, confirmation |
| 2.6-m16 | Operator dashboard (static HTML or simple web UI) | Dashboard renders timeline, breaker state, DLQ, active sessions |

---

## Acceptance Gates (v2.6)

Same philosophy as v2.5.0. Every gate is deterministic, measurable, and reversible.

| Gate | Criterion |
|------|-----------|
| 1 | Full regression suite: 0 failures (including all v2.5.0 tests) |
| 2 | All 12 promotion gates from v2.5.0 still pass |
| 3 | Multi-node failover test: 0 data loss on primary crash |
| 4 | Predictive alert fires before SLO breach in simulated degradation |
| 5 | Policy hot-reload: 0 dropped requests during policy swap |
| 6 | Incident timeline: 100% correlation chain coverage |
| 7 | Chaos suite extended with multi-node failure scenarios |
| 8 | Clean-room rebuild from frozen deps (quarterly baseline) |
| 9 | Soak test: 500+ actions across 2+ nodes, 0 SLO violations |
| 10 | Rollback from v2.6 to v2.5.0 verified in < 60s |

---

## Development Principles

1. **Every milestone ships tests.** No behavioral change without corresponding integration test.
2. **Baseline contract updated at each milestone.** `baseline-contract.json` tracks current known-good state.
3. **Evidence archived per milestone.** `S:\releases\` directory grows with each promoted change.
4. **Rollback always available.** Every milestone can be individually reverted.
5. **No implicit dependencies.** If a milestone requires another, the dependency is declared in its acceptance gate.

---

## Timeline (Estimated)

This is directional, not binding. Actual pace depends on complexity discovered during implementation.

| Phase | Milestones | Estimated Effort |
|-------|-----------|-----------------|
| Phase A | m1-m4 (Multi-node) | Largest scope; foundational |
| Phase B | m5-m8 (Predictive SLO) | Medium scope; builds on existing latency instrumentation |
| Phase C | m9-m12 (Policy-as-Code) | Medium scope; refactors existing policy system |
| Phase D | m13-m16 (Operator UX) | Moderate scope; mostly new UI/API surface |

Phases can be parallelized if independent, but Phase A (multi-node) should land first as it changes the runtime topology that other features build on.
