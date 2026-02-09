# SONIA Issue Register

**Repair ID:** repair_20260208-201157

## Resolved Issues

### ISS-001: Shared library missing critical functions
- **Severity:** P0 (startup blocker)
- **Symptom:** `start-sonia-stack.ps1` crashes with "Get-SoniaRoot is not recognized"
- **Root cause:** `sonia-stack.ps1` was edited/regenerated without `Get-SoniaRoot`, `Ensure-Dir`, `Test-SoniaServiceHealth`, `Wait-SoniaServiceHealth`. Backup files (`.bak.ps1`) contained the original complete version.
- **File(s):** `S:\scripts\lib\sonia-stack.ps1`
- **Fix:** Merged missing functions back into the library while preserving the current `Start-SoniaService`/`Stop-SoniaService` signatures (which the runner scripts depend on).
- **Verification:** Library parse test confirms all 7 functions load correctly.

### ISS-002: PowerShell `$args` automatic variable collision in library
- **Severity:** P0 (silent argument corruption)
- **Symptom:** `Start-SoniaService` silently ignores uvicorn arguments because `$args` is a read-only automatic variable in PowerShell.
- **Root cause:** Variable named `$args` on line 34 of the library.
- **File(s):** `S:\scripts\lib\sonia-stack.ps1`
- **Fix:** Renamed `$args` to `$uvicornArgs`.
- **Verification:** Services start and bind to correct ports.

### ISS-003: PowerShell `$args` collision in main launcher
- **Severity:** P0 (startup blocker)
- **Symptom:** `start-sonia-stack.ps1` line 146 uses `$args` to pass parameters to runner scripts. Same automatic variable collision, and the runner scripts don't accept parameters anyway.
- **Root cause:** Misuse of `$args` + incorrect assumption that runner scripts accept `-Root`/`-Reload` params.
- **File(s):** `S:\start-sonia-stack.ps1`
- **Fix:** Replaced with direct invocation `& $scriptPath` (runner scripts are self-contained).
- **Verification:** Main launcher successfully starts all services.

### ISS-004: Model router `await` on synchronous function
- **Severity:** P1 (runtime crash on specific endpoint)
- **Symptom:** `POST /v1/route` throws `TypeError: object int can't be used in 'await' expression`
- **Root cause:** `main.py` line 145 uses `await route(request.task_type)` but `route()` and the entire call chain through `ProviderRouter.route()` are synchronous.
- **File(s):** `S:\services\model-router\main.py`
- **Fix:** Removed `await` keyword: `return route(request.task_type)`
- **Verification:** Service starts and `/healthz` responds correctly.

### ISS-005: Config health endpoint drift
- **Severity:** P1 (monitoring/tooling mismatch)
- **Symptom:** `sonia-config.json` says `/health` but all services serve `/healthz`
- **Root cause:** Config was written with `/health` but services were implemented with `/healthz`.
- **File(s):** `S:\config\sonia-config.json`
- **Fix:** Updated all 6 service entries from `/health` to `/healthz`.
- **Verification:** Health checks using `/healthz` all pass.

### ISS-006: `start-all.ps1` placeholder
- **Severity:** P1 (ops script non-functional)
- **Symptom:** Running `scripts\ops\start-all.ps1` only prints service names but starts nothing.
- **Root cause:** Script was never completed beyond placeholder `Write-Host` statements.
- **File(s):** `S:\scripts\ops\start-all.ps1`
- **Fix:** Replaced with delegation to canonical launcher `S:\start-sonia-stack.ps1`.
- **Verification:** N/A (canonical launcher verified directly).

### ISS-007: Missing Python dependencies
- **Severity:** P1 (import errors on secondary code paths)
- **Symptom:** `import aiohttp` fails in `api-gateway/api/vision_endpoints.py`; `import yaml` fails if YAML config loading is attempted.
- **Root cause:** Packages not installed in `S:\envs\sonia-core`.
- **File(s):** Environment-level fix
- **Fix:** `pip install aiohttp PyYAML` -> aiohttp 3.13.3, PyYAML 6.0.3
- **Verification:** Both imports succeed.

## Informational (Not Fixed — Low Priority)

### ISS-008: EVA-OS is a skeleton service
- **Severity:** P3 (informational)
- **Detail:** EVA-OS returns hardcoded/stubbed data for `/status`, `/health/all`, `/tasks`, `/approvals`. No actual HTTP client calls to downstream services.

### ISS-009: Orchestrator service is architecturally separate
- **Severity:** P3 (informational)
- **Detail:** Port 8000, uses `/health` not `/healthz`, binds `0.0.0.0`, uses `lifespan` pattern. Not included in boot sequence. Likely a separate development track.

### ISS-010: Deprecated `@app.on_event` lifecycle hooks
- **Severity:** P3 (future maintenance)
- **Detail:** 6 of 7 services use deprecated FastAPI lifecycle hooks. Only orchestrator uses the modern `lifespan` pattern.

### ISS-011: `run-dev.ps1` AppDir mismatch for api-gateway
- **Severity:** P2 (secondary launcher drift)
- **Detail:** `run-dev.ps1` points api-gateway at `S:\apps\api\src` while canonical scripts use `S:\services\api-gateway`. The `run-dev.ps1` script also duplicates launch logic instead of using the shared library.
