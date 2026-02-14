# SONIA v3.0.0 Milestone 1: Contract + Config Cut

## Overview

M1 establishes the v3 API contract, unifies configuration with JSON Schema enforcement and environment variable overlays, and provides a v1 compatibility shim (removal in v3.1.0).

## What Changed

### Version Bump
- `SONIA_VERSION` = `"3.0.0"`
- `SONIA_CONTRACT` = `"v3.0.0"`
- `LEGACY_CONTRACT_V1` = `"v1.x (deprecated, removal in v3.1.0)"`

### Config Schema
- New JSON Schema at `config/schemas/sonia-config.schema.json`
- Validates all config sections, port ranges, required fields
- `config_schema: "3.0.0"` required in config
- Config validator: `services/shared/config_validator.py`

### Environment Variable Overlays
Override any config value without editing JSON:
```
SONIA_MODEL_ROUTER__DEFAULT_MODEL=ollama/qwen2.5:7b
SONIA_MEMORY_ENGINE__LEDGER_PATH=D:\data\memory.db
SONIA_MODEL_ROUTER__OFFLINE_PREFERRED=false
```

Format: `SONIA_{SECTION}__{KEY}={VALUE}` (double underscore separator, case-insensitive). Type coercion is automatic based on the existing value's type.

### API Gateway: V3/V1 Route Split

All existing `/v1/*` endpoints now have `/v3/*` counterparts calling the same handler.

| V3 Endpoint | V1 Endpoint (deprecated) | Method |
|---|---|---|
| `/v3/chat` | `/v1/chat` | POST |
| `/v3/turn` | `/v1/turn` | POST |
| `/v3/action` | `/v1/action` | POST |
| `/v3/deps` | `/v1/deps` | GET |
| `/v3/sessions` | `/v1/sessions` | POST/GET/DELETE |
| `/v3/stream/{id}` | `/v1/stream/{id}` | WS |
| `/v3/ui/stream` | `/v1/ui/stream` | WS |
| `/v3/confirmations/*` | `/v1/confirmations/*` | GET/POST |
| `/v3/actions/*` | `/v1/actions/*` | GET/POST |
| `/v3/capabilities` | `/v1/capabilities` | GET |
| `/v3/health/summary` | `/v1/health/summary` | GET |
| `/v3/breakers/*` | `/v1/breakers/*` | GET/POST |
| `/v3/dead-letters/*` | `/v1/dead-letters/*` | GET/POST |
| `/v3/audit-trails/*` | `/v1/audit-trails/*` | GET |
| `/v3/diagnostics/snapshot` | `/v1/diagnostics/snapshot` | GET |
| `/v3/backups/*` | `/v1/backups/*` | GET/POST |

### Deprecation Headers

All `/v1/*` responses include:
- `X-Deprecated: true`
- `X-Removal-Version: v3.1.0`
- `X-Migrate-To: /v3/...` (path replacement)

V1 response bodies include a `_deprecation` field:
```json
{
  "_deprecation": {
    "deprecated": true,
    "removal_version": "v3.1.0",
    "migrate_to": "/v3/turn",
    "message": "This endpoint is deprecated. Use /v3/turn instead."
  }
}
```

### Service Health Checks

All 8 services now return `contract_version: "v3.0.0"` in their `/healthz` response.

## Migration

Run the migration script:
```powershell
# Preview changes
.\scripts\migrate\v210_to_v300.ps1 -DryRun

# Apply migration
.\scripts\migrate\v210_to_v300.ps1
```

The script:
1. Backs up `config/` and `data/` to `backups/migrate-v300-{timestamp}/`
2. Adds `config_schema: "3.0.0"` to config
3. Updates `sonia_version` to `"3.0.0"`
4. Adds endpoint arrays to `api_gateway` section
5. Validates against JSON Schema
6. Auto-restores backup on validation failure

## Smoke Test

```powershell
# With services running
.\scripts\smoke\smoke_v300_m1.ps1

# Config-only checks (no services needed)
.\scripts\smoke\smoke_v300_m1.ps1 -SkipServices
```

## Tests

18 integration tests in `tests/integration/test_v300_m1_contract.py`:
- 3 version export tests
- 5 config schema tests (valid, invalid, env overlay, services, get_service)
- 5 v3 endpoint tests (healthz, capabilities, chat, turn, deps)
- 4 v1 deprecation tests (headers, body field, migrate-to)
- 1 v1/v3 parity test

## Deprecation Timeline

| Version | Action |
|---|---|
| v3.0.0 (current) | V1 endpoints active with deprecation warnings |
| v3.1.0 | V1 endpoints removed |
