# Stage 3 — Real-time Voice Session Runtime + Tool Safety Gate

## Session API

### POST /v1/sessions — Create session
```json
// Request
{"user_id": "alice", "conversation_id": "conv_123", "profile": "chat_low_latency"}

// Response
{"ok": true, "session_id": "ses_abc123", "created_at": "...", "expires_at": "...", "status": "active"}
```

### GET /v1/sessions/{session_id} — Get session info
Returns session metadata including `turn_count`, `active_streams`, `last_activity`.

### DELETE /v1/sessions/{session_id} — Close session
```json
{"ok": true, "session_id": "ses_abc123", "closed_at": "..."}
```

## Stream Event Protocol

**Endpoint:** `WS /v1/stream/{session_id}`

All events use this envelope:
```json
{"type": "event_type", "session_id": "...", "turn_id": "...", "timestamp": "...", "payload": {...}}
```

### Client → Server Events
| Type | Payload | Description |
|------|---------|-------------|
| `input.text` | `{text: "..."}` | Send text for processing through turn pipeline |
| `input.audio.chunk` | `{data: "base64..."}` | Send audio (relayed to pipecat) |
| `control.ping` | `{}` | Keep-alive |
| `control.cancel` | `{}` | Cancel current processing |
| `control.end_turn` | `{}` | Signal end of input |

### Server → Client Events
| Type | Payload | Description |
|------|---------|-------------|
| `ack` | `{status: "connected"}` | Connection established |
| `response.final` | `{assistant_text: "...", memory: {...}}` | Final response |
| `tool.call.result` | `{tool_name, status, result}` | Tool execution result |
| `safety.confirmation.required` | `{confirmation_id, tool_name, summary, ...}` | Tool needs approval |
| `error` | `{code, message, retryable}` | Error event |

## Confirmation Flow

When model-router requests a guarded tool (file.write, shell.run, browser.open):

1. Gateway emits `safety.confirmation.required` via WebSocket
2. Client checks: `GET /v1/confirmations/pending?session_id=...`
3. Client approves: `POST /v1/confirmations/{id}/approve` → tool executes and result returned
4. Client denies: `POST /v1/confirmations/{id}/deny` → tool skipped

Tool classifications:
- **safe_read**: file.read → executes immediately
- **guarded_write**: file.write, shell.run, browser.open → requires confirmation
- **blocked**: unknown tools → never executed

## Smoke & Soak Commands

```powershell
# Stage 3 smoke test (session + stream + confirmation + Stage 2 regression)
S:\scripts\smoke_stage3_voice.ps1

# Soak test (3 sessions × 2 turns, latency summary)
S:\scripts\soak_stage3_sessions.ps1

# Custom soak parameters
S:\scripts\soak_stage3_sessions.ps1 -Sessions 5 -TurnsPerSession 4
```

## Running Tests

```powershell
# Stage 2 regression (must stay green)
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_turn_pipeline.py -v

# Stage 3 tests
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_session_lifecycle.py -v
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_stream_text_fallback.py -v
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_tool_confirmation_gate.py -v
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_stage2_compat.py -v

# All tests at once
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\ -v
```

## Failure Modes & Quick Triage

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Session create returns MAX_SESSIONS | 100 concurrent session limit hit | Delete stale sessions or restart gateway |
| WebSocket error SESSION_NOT_FOUND | Session expired or not created | Create session first, check TTL (30 min) |
| Stream timeout after 5 minutes | No events sent, idle timeout | Send control.ping to keep alive |
| Confirmation token expired | 120s TTL elapsed before approve/deny | Approve/deny within 2 minutes |
| Model-router 503 in stream | Ollama provider unavailable | Check `ollama list` and model-router logs |

## Structured Logs

JSONL logs are written to `S:\logs\gateway\`:
- `sessions.jsonl` — session create/close events
- `turns.jsonl` — turn completions with latencies
- `tools.jsonl` — tool classification and execution decisions
- `errors.jsonl` — normalized error records

## Ports & Health

| Service | Port | Health |
|---------|------|--------|
| api-gateway | 7000 | GET /healthz |
| model-router | 7010 | GET /healthz |
| memory-engine | 7020 | GET /healthz |
| pipecat | 7030 | GET /healthz |
| openclaw | 7040 | GET /healthz |
| eva-os | 7050 | GET /healthz |
