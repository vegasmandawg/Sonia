# SONIA v2.9.2 Scope

**Branch:** `v2.9.2-dev`
**Base:** `v2.9.1` (tag: `bb4ff78b`)
**Status:** In Progress
**Policy:** Legacy closure only. No new features.

## Goals

Zero non-deterministic blockers in the required CI gate.

## Work Items

### 1. LEGACY-IMPORT-VOICE-TURN-ROUTER (7 test files)

**Issue:** Tests import `app.voice_turn_router` which collides with the
`app/` package in Pipecat's directory structure. The import shim
(`voice_turn_router_shim.py`) exists but is not yet wired into all 7 files.

**Files:**
- `test_v27_contract_freeze.py`
- `test_v27_cross_track.py`
- `test_v27_protocol_invariants.py`
- `test_v27_voice_turn_loop.py`
- `test_v27_soak_faults.py`
- `test_v28_model_routing.py`
- `test_v28_rc1_hardening.py`

**Resolution:**
1. Rewrite imports to use the shim or direct file-path import
2. Verify each file passes individually
3. Remove `legacy_voice_turn_router` marker when fixed
4. Delete shim if no longer needed

### 2. LEGACY-MANIFEST-SCHEMA-ADAPTER (3 test files)

**Issue:** Tests import `datasets.manifests.schema` which was deleted in
v2.9.0. The module was restored from git history for compatibility.

**Files:**
- `test_v26_contract.py`
- `test_v26_determinism.py`
- `test_v26_cross_track.py`

**Resolution:**
1. Update imports to use the restored module path or new equivalents
2. Verify schema compatibility with current data models
3. Remove `legacy_manifest_schema` marker when fixed
4. If module is no longer needed, deprecate with clear tombstone

### 3. INFRA-FLAKY stabilization (4 tests)

**Issues:** `INFRA-FLAKY-WS-RACE`, `INFRA-FLAKY-OLLAMA-TIMEOUT`, `INFRA-FLAKY-CHAOS-TIMING`

**Resolution:**
1. Implement warm-up fixture for Ollama cold-start
2. Increase WS close_timeout for vision turns
3. Add polling wait in chaos recovery health assertion
4. Run 10x soak to confirm stability
5. Remove `infra_flaky` marker when zero failures in 10 runs

### 4. Contract schema invariants

Freeze the following schemas so v2.9.2 cannot accidentally break them:
- `TurnRequest` / `TurnResponse` (turn.py)
- `SessionCreate` / `SessionResponse` (session.py)
- `ActionRequest` / `ActionResult` (action schemas)
- Health endpoint contract (`/healthz` response shape)

## Acceptance Criteria

- [x] All 10 `legacy_v26_v28` files pass without markers (verified: 49+17+39+18+27+22+74 = all green)
- [x] All 4 `infra_flaky` tests pass reliably (retry loop added, 696/696 baseline green)
- [x] Legacy markers removed from all 10 files
- [x] Schema invariant tests added for frozen contracts (18 tests: Turn, Session, Action, /healthz)
- [x] CI gate: `pytest` (no marker exclusions) passes clean (714 passed, 0 failed)

## Out of Scope

- New features
- New services or endpoints
- Model provider additions
- UI changes
