# SONIA Auto-Repair: Executive Summary

**Date:** 2026-02-08
**Repair ID:** repair_20260208-201157
**Operator:** Autonomous repair agent

## Architecture Discovered

SONIA is a local-first AI assistant built as a FastAPI multi-service stack on Windows 11:

| Service | Port | Role |
|---|---|---|
| API Gateway | 7000 | Front door, input normalization, routing to downstream services |
| Model Router | 7010 | LLM provider selection (Ollama local, Anthropic, OpenRouter) |
| Memory Engine | 7020 | Persistence layer, SQLite-backed ledger and knowledge store |
| Pipecat | 7030 | Real-time modality gateway, voice I/O, WebSocket sessions |
| OpenClaw | 7040 | Action executor, tool catalog (4 tools registered) |
| EVA-OS | 7050 | Supervisory control plane, orchestration (skeleton) |

**Orchestrator service** (port 8000) exists but is architecturally separate and not part of the main boot sequence.

**Python environment:** `S:\envs\sonia-core\python.exe` (conda prefix env, Python + FastAPI 0.116.1 + uvicorn 0.35.0)

## What Was Broken

1. **Shared library truncated (P0):** `scripts\lib\sonia-stack.ps1` was missing 3 critical functions (`Get-SoniaRoot`, `Ensure-Dir`, `Test-SoniaServiceHealth`) that the main launcher depends on. The main `start-sonia-stack.ps1` would crash immediately on load.

2. **PowerShell `$args` variable collision (P0):** Both the shared library and the main launcher used `$args` as a local variable name. In PowerShell, `$args` is an automatic read-only variable. This caused silent failures in argument passing.

3. **Model router `await` on sync function (P1):** `model-router/main.py` line 145 used `await route()` on a synchronous function, causing a runtime TypeError on any `/v1/route` request.

4. **Health endpoint config drift (P1):** `sonia-config.json` listed `/health` as the health endpoint for all services, but all services actually serve `/healthz`.

5. **`start-all.ps1` was a non-functional placeholder (P1):** Only printed service names without starting anything.

6. **Missing Python dependencies (P1):** `aiohttp` and `PyYAML` were not installed in the sonia-core environment.

## What Was Fixed

- Restored `Get-SoniaRoot`, `Ensure-Dir`, `Test-SoniaServiceHealth`, `Wait-SoniaServiceHealth` to the shared library
- Renamed `$args` to `$uvicornArgs` in library; removed broken `$args` splatting in launcher
- Removed erroneous `await` from model-router sync call
- Updated all 6 health endpoints in config from `/health` to `/healthz`
- Replaced `start-all.ps1` placeholder with delegation to canonical launcher
- Installed `aiohttp` (3.13.3) and `PyYAML` (6.0.3)

## Final Stack Status

**SONIA Stack: HEALTHY**

All 6 services started, listening, and passing health checks. All 8 smoke tests passed. Full health matrix verified.
