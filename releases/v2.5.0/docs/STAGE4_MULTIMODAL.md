# Stage 4 — Multimodal Live Operation & Memory Quality Controls

## Overview

Stage 4 adds vision ingestion, turn quality controls, memory write/retrieval
policies, confirmation idempotency, and latency instrumentation to the
existing session/stream runtime.

## New Stream Events

### Client → Server

| Event                      | Payload                                     |
|----------------------------|---------------------------------------------|
| `input.vision.frame`      | `{frame_id, mime_type, data (base64)}`      |
| `input.vision.snapshot`   | `{frame_id, mime_type, data (base64)}`      |
| `control.vision.enable`   | `{max_frame_bytes?, max_frames_per_minute?}` |
| `control.vision.disable`  | `{}`                                        |

### Server → Client

| Event                  | Payload                                      |
|------------------------|----------------------------------------------|
| `vision.accepted`     | `{frame_id, size_bytes, mime_type}`          |
| `vision.rejected`     | `{code, message, frame_id, retryable}`       |

### Combined Text + Vision Turn

Send `input.text` with extra fields in payload:

```json
{
  "type": "input.text",
  "payload": {
    "text": "What do you see?",
    "vision_data": "<base64-png>",
    "vision_mime": "image/png"
  }
}
```

The `response.final` payload now includes:

```json
{
  "assistant_text": "...",
  "memory": {"written": true, "retrieved_count": 3},
  "quality": {
    "generation_profile_used": "chat_low_latency",
    "fallback_used": false,
    "tool_calls_attempted": 0,
    "tool_calls_executed": 0,
    "completion_reason": "ok"
  },
  "has_vision": true,
  "latency": {}
}
```

## Vision Limits (Configurable)

| Parameter               | Default   |
|-------------------------|-----------|
| `max_frame_bytes`       | 1 MiB     |
| `max_frames_per_minute` | 10        |
| `max_frames_per_turn`   | 3         |
| Allowed MIME types      | image/png, image/jpeg, image/webp, image/gif |

## Turn Quality Annotations

Every `response.final` and sync `/v1/turn` response includes:

- `quality.generation_profile_used` — which profile was used
- `quality.fallback_used` — whether the fallback profile was needed
- `quality.tool_calls_attempted` / `tool_calls_executed`
- `quality.completion_reason` — `ok`, `fallback`, `timeout`, `error`

## Latency Breakdown

The `/v1/turn` response includes a `latency` object:

```json
{
  "asr_ms": 0,
  "vision_ms": 5.2,
  "memory_read_ms": 12.3,
  "model_ms": 350.1,
  "tool_ms": 0,
  "memory_write_ms": 8.7,
  "total_ms": 376.3
}
```

## Memory Policy

### Write Policy
- Stores `turn_raw` (full transcript) + `turn_summary` (compact)
- Tags: `turn_raw`, `turn_summary`, `tool_event`, `confirmation_event`, `vision_observation`
- All writes include `session_id`, `turn_id`, timestamps
- Write failures are **non-fatal**: response returns `memory.written=false`

### Retrieval Policy
- Bounded context token budget (default 2000 chars)
- Prefers summaries over raw content
- Type-filtered search

## Confirmation Idempotency

- **Approve after approve** → returns `{ok: true, idempotent: true}`
- **Deny after deny** → returns `{idempotent: true}`
- **Approve after deny** → returns denied status (no flip)
- **Deny after approve** → returns approved status (no flip)
- **Expired tokens** → return `CONFIRMATION_EXPIRED` code

## Smoke / Soak Usage

```powershell
# Smoke
powershell -File S:\scripts\smoke_stage4_multimodal.ps1

# Soak (defaults: 3 sessions, 2 turns each)
powershell -File S:\scripts\soak_stage4_multimodal.ps1

# Custom soak
powershell -File S:\scripts\soak_stage4_multimodal.ps1 -Sessions 5 -TurnsPerSession 4
```

## Troubleshooting

### 1. Invalid frame encoding
**Symptom**: `vision.rejected` with code `INVALID_BASE64`
**Fix**: Ensure `data` field is valid base64. Use `base64.b64encode(raw_bytes).decode()`.

### 2. Model-router vision profile mismatch
**Symptom**: 400/503 from model-router when task_type=vision
**Fix**: Check `S:\services\model-router\providers.py` has VISION in TaskType enum.
Fallback to text profile is automatic when `fallback_on_model_timeout=true`.

### 3. Memory write failure
**Symptom**: `memory.written=false` in response; errors in `S:\logs\gateway\errors.jsonl`
**Fix**: Check memory-engine health: `curl http://127.0.0.1:7020/healthz`.
Turn still succeeds; memory failure is non-fatal by design.

### 4. Confirmation expiry / idempotency mismatch
**Symptom**: `CONFIRMATION_EXPIRED` when approving
**Fix**: Confirmations expire after 120s. Approve within TTL window.
Repeated approve/deny is safe (idempotent).

### 5. WebSocket disconnect mid-turn
**Symptom**: Client loses connection during `input.text` processing
**Fix**: The stream handler catches all errors and cleans up session state.
Reconnect with a new WebSocket to the same session_id.
