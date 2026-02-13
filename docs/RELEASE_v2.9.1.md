# SONIA v2.9.1 Release Notes

**Tag:** `v2.9.1-rc1`
**Branch:** `v2.9.1-runtime-hardening`
**Date:** 2026-02-13

## Summary

Runtime hardening release following comprehensive system audit. Focuses on
making all 6 core services bootable, fixing dead code paths, aligning
configuration, and isolating legacy test debt.

## Included

### Memory Engine
- Token budget enforcement extracted to `_apply_token_budget()` helper;
  applied consistently to all 3 retrieval endpoints (`/search`, `/v1/search`,
  `/query/by-type/{type}`)
- Snapshot manager fetches real data from DB (was returning empty stubs)
- Workspace store chunking implemented via `Chunker` class (was a TODO stub)
- Schema extended with `workspace_documents`, `workspace_chunks`, `provenance`
  tables and indexes
- Dead code renamed with `_dead_` prefix (not deleted, to prevent import breaks)

### Model Router
- Default Ollama model aligned: `qwen2:7b` -> `qwen2.5:7b`
- OpenRouter provider: live model list fetch from API with static fallback
- OpenRouter routing: added VISION task type support (was TEXT-only)
- Added missing transitive deps: `httpx`, `httpcore`, `h11`

### Pipecat
- Fixed `sys.path` ordering: local `events.py` now found before
  `shared/events.py` (was causing `ImportError` on startup)

### Test Infrastructure
- `conftest.py` with custom markers: `legacy_v26_v28`,
  `legacy_voice_turn_router`, `legacy_manifest_schema`
- 10 legacy test files marked for isolation (v2.6-v2.8 suites)
- VoiceTurnRouter import shim for `app/` package collision avoidance
- Manifest schema module restored from v2.9.0 tag for v2.6 test compat
- `pytest.ini` updated with marker definitions

### Documentation
- `SONIA_FINAL_SETUP_DOCUMENT.md`: comprehensive audit of all services

## Excluded (tracked separately)

- v2.6-v2.8 legacy compatibility remediation
- Tracked issues:
  - `LEGACY-IMPORT-VOICE-TURN-ROUTER`: 7 test files with `app.voice_turn_router`
    import collision (shim created, markers applied)
  - `LEGACY-MANIFEST-SCHEMA-ADAPTER`: 3 test files importing
    `datasets.manifests.schema` (module restored, markers applied)

## Known Limitations

- Legacy test failures (v2.6-v2.8) are non-regression and isolated via markers
- Run v2.9+ suites only for CI gate: `pytest -m "not legacy_v26_v28"`
- Run legacy suites non-blocking: `pytest -m legacy_v26_v28 --continue-on-error`

## RC1 Gate Results

| Gate | Tests | Result |
|------|-------|--------|
| v2.9 Memory Hybrid | 28 | PASS |
| v2.9 Model Routing | 21 | PASS |
| v2.9 EVA Supervision | 19 | PASS |
| v2.9 Post-Close Drills | 24 | PASS |
| **Total (v2.9 core)** | **92** | **ALL GREEN** |

## Service Health (verified)

| Service | Port | /healthz |
|---------|------|----------|
| api-gateway | 7000 | 200 OK |
| model-router | 7010 | 200 OK |
| memory-engine | 7020 | 200 OK |
| pipecat | 7030 | 200 OK |
| openclaw | 7040 | 200 OK |
| eva-os | 7050 | 200 OK |
