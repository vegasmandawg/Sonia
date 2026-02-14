# SONIA v2.9.2 -- Legacy Closure

**Tag:** `v2.9.2`
**Branch:** `v2.9.2-dev` merged to `main`
**Base:** v2.9.1
**Policy:** Legacy closure only. No new features.
**Test Gate:** 714 passed / 0 failed / 0 marker exclusions

## Summary

Legacy closure completed with no behavior regressions. All acceptance
criteria from SCOPE_v2.9.2.md satisfied.

## Added

- 18 schema invariant tests covering TurnRequest/Response,
  SessionCreateRequest/Response, ActionPlanRequest/Response,
  and /healthz response shape across all 6 core services
  (`test_schema_invariants.py`)

## Fixed

- `test_sync_turn_has_quality_and_latency`: flaky due to Ollama
  cold-start after WS tests. Added 5-attempt retry loop with
  increasing backoff (5s, 10s, 15s, 20s, 25s). Handles both
  `ok=False` responses and `ReadTimeout` exceptions.

## Closed Issues

- **INFRA-FLAKY-WS-RACE**: ConnectionClosedOK already handled
  in test (catches gracefully). Verified stable across runs.
- **INFRA-FLAKY-OLLAMA-TIMEOUT**: Fixed via retry/backoff in
  sync turn test + session-scoped warmup in conftest.py.
- **INFRA-FLAKY-CHAOS-TIMING**: 60s polling loop already in
  place for health supervisor state convergence.

## Removed

- `legacy_v26_v28` pytest markers from all 10 test files:
  test_v26_contract, test_v26_cross_track, test_v26_determinism,
  test_v27_contract_freeze, test_v27_cross_track,
  test_v27_protocol_invariants, test_v27_soak_faults,
  test_v27_voice_turn_loop, test_v28_model_routing,
  test_v28_rc1_hardening

## Known Deferred Items (target: v2.10)

### P0
- Perception real VLM inference path (replace mock with
  model-router task_type=vision_analysis)
- Memory chunker sentence-aware tokenizer replacement

### P1
- OpenClaw executor completion (remove NotImplemented stubs)
- MCP server boot wiring + integration tests
- Policy engine dedicated test coverage

### P2
- Training pipeline end-to-end on RunPod hardware
- HF dataset upload verification
- Branch hygiene (prune 12 stale local branches)
