# SONIA v3.0.0 Milestone 2: Identity + Persistence

## Overview

M2 adds local API key authentication, durable session persistence, and conversation history storage. All data lives in the existing `memory.db` SQLite database (no new services or external dependencies).

## What Changed

### User Identity

New `users` table in memory.db with SHA-256 hashed API keys.

- `POST /v1/users` -- Create user, returns API key (shown once)
- `GET /v1/users/{user_id}` -- Get user profile (no key)
- `PUT /v1/users/{user_id}` -- Update display_name/metadata
- `DELETE /v1/users/{user_id}` -- Soft-delete (status=deleted)
- `POST /v1/users/{user_id}/rotate-key` -- Generate new key
- `GET /v1/users/by-key?api_key_hash=...` -- Internal lookup by hash

### API Key Authentication

Auth middleware on API Gateway validates `Authorization: Bearer <key>` headers.

- Enabled/disabled via `auth.enabled` in sonia-config.json (default: false)
- Exempt paths: `/healthz`, `/status`, `/docs`, `/openapi.json`, `/redoc`
- Service-to-service: `X-Service-Token` header bypasses user auth
- Key cache: LRU with TTL to avoid per-request DB calls

### Session Persistence

Sessions now survive gateway restarts. The in-memory `SessionManager` writes through to memory-engine SQLite.

- On create: async persist to `sessions` table
- On delete: async update status
- On touch/increment_turn: batch persist (every 5 touches or 60s)
- On startup: restore active sessions from DB
- In-memory cache remains the fast path

### Conversation History

Turn results are durably stored for replay and analysis.

- Fire-and-forget writes (don't block turn response)
- Stored in `conversation_turns` table with session_id, user_id, sequence_num
- Query by session (ordered) or by user (across sessions)

## Database Schema

### users
| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT PK | `usr_{uuid}` |
| display_name | TEXT | User display name |
| api_key_hash | TEXT | SHA-256 of API key |
| created_at | TEXT | ISO 8601 timestamp |
| updated_at | TEXT | ISO 8601 timestamp |
| status | TEXT | active/suspended/deleted |
| metadata | TEXT | JSON |

### sessions
| Column | Type | Description |
|--------|------|-------------|
| session_id | TEXT PK | `ses_{uuid}` |
| user_id | TEXT FK | References users |
| conversation_id | TEXT | Conversation group |
| profile | TEXT | Model profile |
| status | TEXT | active/closed/expired |
| created_at/expires_at/last_activity | TEXT | Timestamps |
| turn_count | INTEGER | Turns in session |
| metadata | TEXT | JSON |

### conversation_turns
| Column | Type | Description |
|--------|------|-------------|
| turn_id | TEXT PK | Unique turn ID |
| session_id | TEXT FK | References sessions |
| user_id | TEXT FK | References users |
| sequence_num | INTEGER | Order within session |
| user_input | TEXT | User message |
| assistant_response | TEXT | Model response |
| model_used | TEXT | Model identifier |
| tool_calls | TEXT | JSON array of tool invocations |
| latency_ms | REAL | Turn latency |
| metadata | TEXT | JSON (quality annotations) |
| created_at | TEXT | ISO 8601 timestamp |

## Configuration

New `auth` section in `sonia-config.json`:

```json
{
  "auth": {
    "enabled": false,
    "exempt_paths": ["/healthz", "/status", "/docs", "/openapi.json"],
    "service_token": "",
    "key_cache_ttl_seconds": 300,
    "key_cache_max_entries": 100
  }
}
```

Set `enabled: true` and optionally set `service_token` to a shared secret for inter-service calls.

## Key Management

```powershell
# Create a new user
.\scripts\manage-keys.ps1 -Create -DisplayName "Sonia UI"

# List all users
.\scripts\manage-keys.ps1 -List

# Rotate a key
.\scripts\manage-keys.ps1 -Rotate -UserId "usr_xxxx"

# Revoke access
.\scripts\manage-keys.ps1 -Revoke -UserId "usr_xxxx"
```

## Tests

20 integration tests in `tests/integration/test_v300_m2_identity.py`:
- 6 user CRUD tests
- 4 API key management tests
- 5 session persistence tests
- 4 conversation history tests
- 6 auth middleware unit tests
- 3 session manager persistence tests

## Smoke Test

```powershell
# With services running
.\scripts\smoke\smoke_v300_m2.ps1

# Skip live service checks
.\scripts\smoke\smoke_v300_m2.ps1 -SkipServices
```
