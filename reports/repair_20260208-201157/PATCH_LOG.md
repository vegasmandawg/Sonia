# SONIA Patch Log

**Repair ID:** repair_20260208-201157
**Backups:** `S:\reports\repair_20260208-201157\backups\`

## File Changes

### 1. `S:\scripts\lib\sonia-stack.ps1`
- **Before:** 88 lines. Only contained `Test-PortListen`, `Start-SoniaService`, `Stop-SoniaService`. Used `$args` (automatic variable) on line 34.
- **After:** 182 lines. Added `Get-SoniaRoot`, `Ensure-Dir`, `Test-SoniaServiceHealth`, `Wait-SoniaServiceHealth`. Renamed `$args` to `$uvicornArgs`.
- **Behavior change:** Library now provides all functions required by the main launcher. Service start arguments are correctly passed.
- **Rollback:** Copy `backups\scripts\lib\sonia-stack.ps1` back.

### 2. `S:\start-sonia-stack.ps1`
- **Before:** Line 146-148 used `$args = @("-Root", $root)` and splatted to runner scripts.
- **After:** Line 146 simplified to `& $scriptPath` (runner scripts are self-contained).
- **Behavior change:** Runner scripts invoked directly without broken parameter passing.
- **Rollback:** Copy `backups\start-sonia-stack.ps1` back.

### 3. `S:\services\model-router\main.py`
- **Before:** Line 145: `return await route(request.task_type)`
- **After:** Line 145: `return route(request.task_type)`
- **Behavior change:** `/v1/route` endpoint no longer throws TypeError.
- **Rollback:** Copy `backups\services\model-router\main.py` back.

### 4. `S:\config\sonia-config.json`
- **Before:** All 6 services had `"health_endpoint": "/health"`
- **After:** All 6 services have `"health_endpoint": "/healthz"`
- **Behavior change:** Config matches actual service implementation.
- **Rollback:** Copy `backups\config\sonia-config.json` back.

### 5. `S:\scripts\ops\start-all.ps1`
- **Before:** Placeholder with only `Write-Host` statements.
- **After:** Delegates to `S:\start-sonia-stack.ps1`.
- **Behavior change:** Script now actually starts services.
- **Rollback:** Copy `backups\scripts\ops\start-all.ps1` back.

### 6. Python environment (`S:\envs\sonia-core`)
- **Change:** Installed `aiohttp==3.13.3` and `PyYAML==6.0.3` via pip.
- **Rollback:** `pip uninstall aiohttp PyYAML`
