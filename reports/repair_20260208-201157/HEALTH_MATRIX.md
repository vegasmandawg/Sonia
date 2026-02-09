# SONIA Health Matrix

**Timestamp:** 2026-02-09T02:15:49Z
**Repair ID:** repair_20260208-201157

## Service Health

| Service | Port | PID | Listening | Process Alive | /healthz | / (root) | Status |
|---|---|---|---|---|---|---|---|
| api-gateway | 7000 | 35812 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |
| model-router | 7010 | 19900 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |
| memory-engine | 7020 | 46176 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |
| pipecat | 7030 | 26760 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |
| openclaw | 7040 | 40916 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |
| eva-os | 7050 | 6536 | Yes | Yes | 200 OK | 200 OK | **HEALTHY** |

## Smoke Test Results

| Test | Endpoint | Result | Notes |
|---|---|---|---|
| GW Dependencies | GET /v1/deps | PASS | memory-engine OK, model-router OK, openclaw OK, pipecat pending |
| GW Status | GET /status | PASS | online, v1.0.0 |
| MR Status | GET /status | PASS | 1 provider (ollama), 5 models |
| ME Status | GET /status | PASS | SQLite connected, 0 memories |
| OC Status | GET /status | PASS | 4 tools registered, 4 implemented |
| PC Status | GET /status | PASS | online, sessions active |
| EO Status | GET /status | PASS | normal mode, all services healthy |
| EO Health/All | GET /health/all | PASS | All 5 downstream services healthy |

## Overall Stack Status: HEALTHY
