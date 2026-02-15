# SONIA v3.0.0 — Milestone 4: Perception Memory Bridge

## Overview

M4 bridges the perception subsystem to the typed memory ledger. Scene
analysis outputs (entities, summaries, recommended actions) are converted
into typed FACT and SYSTEM_STATE memories with full provenance tracking.
All recommended actions are gated through the PerceptionActionGate
confirmation flow before execution, with confirmation state changes
recorded as immutable version chain entries.

## Architecture

### PerceptionMemoryBridge (`perception_memory_bridge.py`)

Core bridge class with three public methods:

- **`ingest_scene(scene_analysis, session_id, correlation_id)`**
  Converts a SceneAnalysis dict into typed memories:
  - Each entity -> FACT (`subject=label`, `predicate=detected_in_scene`)
  - Scene summary -> FACT (`subject=scene_id`, `predicate=scene_summary`)
  - Recommended action -> SYSTEM_STATE (`component=perception`, `health_status=pending_confirmation`)

- **`bind_action_confirmation(scene_analysis, gate, session_id, correlation_id)`**
  Gates a perception-recommended action through PerceptionActionGate.
  Records the pending confirmation as a SYSTEM_STATE memory with
  `requirement_id` in metadata.

- **`on_confirmation_resolved(requirement, resolution, correlation_id)`**
  Records confirmation resolution (approved/denied) as a new version of
  the SYSTEM_STATE memory, creating an immutable audit trail.

### Provenance Tracking (`core/provenance.py`)

Extended with `track_perception()`:
- Validates 4 required fields: `scene_id`, `correlation_id`, `trigger`, `model_used`
- Raises `ValueError` on empty/missing fields (fail-fast, no silent drops)
- Persists to `audit_log` table with `operation=PROVENANCE`
- In-memory index for fast lookups + DB fallback

### Provenance Endpoint (`memory-engine/main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/provenance/track` | Record provenance for a memory item |
| GET | `/v1/provenance/{memory_id}` | Retrieve provenance record |

### Data Contracts

**PerceptionIngestResult** (dataclass):
```
scene_id: str
memory_ids: List[str]
entity_count: int
conflicts: List[Dict]
errors: List[str]
provenance_source: str = "perception"
correlation_id: str
confirmation_requirement_id: Optional[str]
```

**Perception FACT content** (JSON):
```json
{
  "subject": "<entity_label>",
  "predicate": "detected_in_scene",
  "object": "<scene_id>",
  "confidence": 0.9,
  "source": "perception"
}
```

**Perception SYSTEM_STATE content** (JSON):
```json
{
  "component": "perception",
  "state_key": "recommended_action",
  "state_value": "<action_name>",
  "health_status": "pending_confirmation"
}
```

**Provenance metadata** (per memory):
```
scene_id, session_id, correlation_id, trigger, model_used,
inference_ms, privacy_verified, source_type="perception"
```

## Key Invariants

1. Every perception-derived memory has `source_type="perception"` in metadata
2. Every recommended action is gated via PerceptionActionGate (no bypass)
3. Confirmation state changes are recorded as SYSTEM_STATE versions (immutable trail)
4. `valid_from` = scene timestamp (business time), `valid_until` = None (current)
5. `track_perception()` rejects empty required fields with ValueError
6. `_write_typed()` and `_track_provenance()` never raise (best-effort, errors captured)
7. Confirmation binding is one-shot: double-execute raises ConfirmationBypassError
8. Expired/denied/pending requirements cannot be validated for execution

## Safety and Governance

- **Non-bypassable confirmation**: PerceptionActionGate enforces one-shot approval;
  expired, denied, pending, and already-executed requirements all raise
  `ConfirmationBypassError`
- **Side-effect controls**: `_write_typed()` catches all exceptions; provenance
  tracking is best-effort (logged, never fatal)
- **Audit trail**: Every confirmation state change creates a new version chain
  entry with `resolution` in metadata (approved/denied)
- **Correlation IDs**: Propagated through all bridge operations for end-to-end
  traceability

## Performance Notes

- Bridge operations are async; no blocking I/O in the hot path
- Provenance tracking uses `httpx` with 5s timeout (non-blocking, best-effort)
- Entity ingestion is O(n) on entity count; bounded by SceneAnalysis limits
  (max entities set upstream in perception service)
- No additional DB indexes required (uses existing `audit_log` table)

## Test Coverage

28 integration tests in `test_v300_m4_perception.py`:

| Group | Count |
|-------|-------|
| Perception -> Typed Memory | 7 |
| Provenance Chain | 4 |
| Confirmation Binding | 4 |
| Conflict Detection | 3 |
| No-Bypass Enforcement | 5 |
| Version Chain Integration | 3 |
| Adversarial | 2 |

Regression: M3 (38 tests) + M2 (28 tests) + M1 (18 tests) all green.

## Files Changed

| File | Action |
|------|--------|
| `services/api-gateway/perception_memory_bridge.py` | Create |
| `services/memory-engine/core/provenance.py` | Modify |
| `services/memory-engine/main.py` | Modify |
| `tests/integration/test_v300_m4_perception.py` | Create |
| `tests/integration/test_v300_m3_memory.py` | Modify (test count) |
| `docs/V3_M3_MEMORY_LEDGER.md` | Modify (cross-ref) |
| `docs/V3_M4_PERCEPTION_BRIDGE.md` | Create |

## Known Limitations

- Provenance tracking is best-effort over HTTP; if memory-engine is down,
  provenance records are lost (bridge continues without error)
- No batch ingestion API; scenes are processed one at a time
- Confirmation TTL is set per-gate instance, not configurable per-action

## Rollback Plan

- Remove `perception_memory_bridge.py` from api-gateway
- Revert `provenance.py` additions (`track_perception()`)
- Revert `main.py` provenance endpoint additions
- M3 typed memory and version chains remain unaffected (backward compatible)
- No schema migrations in M4; no DB rollback needed

## Commit

- **SHA**: `be5b858`
- **Date**: 2026-02-14
- **Message**: `feat(v3.0-m4): perception memory bridge -- typed memory binding, confirmation gating, provenance tracking`
