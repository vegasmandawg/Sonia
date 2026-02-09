# Turn Pipeline — Stage 2 Functional Integration

## Overview

The `/v1/turn` endpoint on api-gateway (port 7000) implements a full
end-to-end conversational turn:

```
client → api-gateway /v1/turn
           ├── memory-engine /search   (recall context)
           ├── model-router  /chat     (generate response)
           ├── openclaw      /execute  (tool calls, if any)
           └── memory-engine /store    (persist turn record)
```

## Endpoint

**POST** `http://127.0.0.1:7000/v1/turn`

### Request

```json
{
  "user_id": "alice",
  "conversation_id": "conv_abc123",
  "input_text": "What is the capital of France?",
  "profile": "chat_low_latency",
  "metadata": {}
}
```

| Field             | Type   | Required | Default              |
|-------------------|--------|----------|----------------------|
| `user_id`         | string | yes      |                      |
| `conversation_id` | string | yes      |                      |
| `input_text`      | string | yes      |                      |
| `profile`         | string | no       | `chat_low_latency`   |
| `metadata`        | object | no       | `null`               |

### Response

```json
{
  "ok": true,
  "turn_id": "turn_a1b2c3d4e5f67890",
  "assistant_text": "The capital of France is Paris.",
  "tool_calls": null,
  "tool_results": null,
  "memory": {
    "written": true,
    "retrieved_count": 3
  },
  "duration_ms": 1842.5
}
```

On error the response includes `"ok": false` and an `"error"` object:

```json
{
  "ok": false,
  "turn_id": "turn_...",
  "assistant_text": "",
  "memory": { "written": false, "retrieved_count": 0 },
  "duration_ms": 52.1,
  "error": { "code": "UNAVAILABLE", "message": "Model Router unavailable: ..." }
}
```

## Running the Smoke Script

```powershell
S:\scripts\smoke_turn.ps1
```

Checks all 6 service health endpoints, calls `/v1/turn` twice, and prints
PASS/FAIL for each check.  Exits with code 0 on full pass, 1 on failure.

## Running Integration Tests

```powershell
S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_turn_pipeline.py -v
```

Requires the full stack to be running.  Tests cover response shape,
non-empty assistant text, unique turn IDs, memory write, and memory
retrieval on a second call.

## Service Ports and Health Endpoints

| Service        | Port | Health           |
|----------------|------|------------------|
| api-gateway    | 7000 | `GET /healthz`   |
| model-router   | 7010 | `GET /healthz`   |
| memory-engine  | 7020 | `GET /healthz`   |
| pipecat        | 7030 | `GET /healthz`   |
| openclaw       | 7040 | `GET /healthz`   |
| eva-os         | 7050 | `GET /healthz`   |

## Troubleshooting

**Model-router returns 503 or empty response**
- Verify Ollama is running: `ollama list` should show `qwen2:7b`.
- Check model-router logs in `S:\logs\services\model-router\`.
- The `/chat` endpoint requires at least one healthy provider.

**Memory-engine search returns 0 results on second call**
- memory-engine uses SQLite FTS5 LIKE-based search; very short queries
  may not match.  The test uses a descriptive sentence to maximise hit
  probability.
- Verify the DB exists: `S:\data\memory\ledger.db`.
