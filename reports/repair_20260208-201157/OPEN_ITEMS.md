# SONIA Open Items

**Repair ID:** repair_20260208-201157

## Unresolved (Low Priority)

### OPEN-001: EVA-OS is a skeleton
- **Impact:** Low. Service runs and responds healthily, but all data is hardcoded/stubbed.
- **Next action:** Implement actual HTTP clients in EVA-OS to poll downstream services for real health data. Replace hardcoded `/tasks` and `/approvals` with real implementations.

### OPEN-002: Orchestrator service not integrated
- **Impact:** Low. Separate architectural track, port 8000.
- **Next action:** Decide whether orchestrator should be merged into EVA-OS or remain separate. If kept, align health endpoint to `/healthz`, bind to `127.0.0.1`, and add to boot sequence.

### OPEN-003: `run-dev.ps1` points api-gateway to wrong directory
- **Impact:** Medium (if anyone uses `run-dev.ps1`). Points to `S:\apps\api\src` instead of `S:\services\api-gateway`.
- **Next action:** Update `run-dev.ps1` to use `S:\services\api-gateway` or deprecate in favor of canonical launcher.

### OPEN-004: Deprecated FastAPI lifecycle hooks
- **Impact:** Low (works with current FastAPI version, may warn in future).
- **Next action:** Migrate `@app.on_event("startup")`/`@app.on_event("shutdown")` to `lifespan` context manager in all 6 services.

### OPEN-005: Memory Engine bare except clauses
- **Impact:** Low (can mask unexpected errors).
- **Next action:** Replace bare `except:` with `except Exception:` or specific exception types in `memory-engine/main.py` lines 136, 165, 205, 259.

### OPEN-006: Pipecat integration with API Gateway marked "pending"
- **Impact:** Low. The `/v1/deps` endpoint reports pipecat as `"status": "pending"`.
- **Next action:** Complete Pipecat client integration in API Gateway when voice pipeline is ready.

## No Hard Blockers Remain
All startup-blocking and runtime-crash issues have been resolved.
