# Sonia Stack Bootstrap Guide

## Overview

This guide walks you through starting the bootable Sonia stack. The system is now ready to launch with all required startup scripts and service entry points in place.

## Architecture

The Sonia stack consists of 6 services:

| Service | Port | Purpose |
|---------|------|---------|
| **API Gateway** | 7000 | Front door, request routing, UI transport |
| **Model Router** | 7010 | Model/provider selection and routing |
| **Memory Engine** | 7020 | Persistent storage, vector indexing, retrieval |
| **Pipecat** | 7030 | Real-time voice I/O, audio streaming |
| **OpenClaw** | 7040 | Action executor, tool service, verification |
| **EVA-OS** | 7050 | Orchestration, policy, health monitoring |

All services are FastAPI applications running on localhost.

## Quick Start

### 1. Start the Stack

From the root directory (S:\):

```powershell
.\start-sonia-stack.ps1
```

With reload enabled (for development):

```powershell
.\start-sonia-stack.ps1 -Reload
```

### 2. Verify Services Are Running

Check individual service health:

```powershell
iwr http://127.0.0.1:7000/healthz  # API Gateway
iwr http://127.0.0.1:7010/healthz  # Model Router
iwr http://127.0.0.1:7020/healthz  # Memory Engine
iwr http://127.0.0.1:7030/healthz  # Pipecat
iwr http://127.0.0.1:7040/healthz  # OpenClaw
iwr http://127.0.0.1:7050/healthz  # EVA-OS
```

All should return `{"ok": true, "service": "<name>", ...}`

### 3. Stop the Stack

```powershell
.\stop-sonia-stack.ps1
```

## Installation & Configuration

### Prerequisites

- **Python 3.11+** (in PATH or `S:\envs\sonia-core\`)
- **FastAPI and Uvicorn**: Installed automatically on first start
- **Windows PowerShell** (Core or Desktop Edition)

### First Run Configuration

1. **Copy environment template** (optional):
   ```powershell
   Copy-Item .env.example .env
   ```

2. **Create required directories**:
   - `S:\state\pids\` - PID files (auto-created)
   - `S:\logs\services\` - Service logs (auto-created)
   - `S:\data\` - Data directory (should already exist)

3. **Configure environment variables**:
   - Edit `.env` for API keys, model endpoints, etc.
   - At minimum, set `OLLAMA_ENDPOINT` if using local models

### Python Environment

The stack automatically discovers Python:

1. Checks `S:\envs\sonia-core\python.exe` (preferred)
2. Falls back to `python` in PATH
3. Installs dependencies on first run

To manually install dependencies:

```powershell
pip install fastapi uvicorn pydantic
```

## Key Files & Directories

### Startup Scripts
- `S:\start-sonia-stack.ps1` - Start all services
- `S:\stop-sonia-stack.ps1` - Stop all services
- `S:\scripts\ops\run-*.ps1` - Individual service launchers
- `S:\scripts\lib\sonia-stack.ps1` - Shared library functions

### Service Entry Points
- `S:\services\api-gateway\main.py`
- `S:\services\model-router\main.py`
- `S:\services\memory-engine\main.py`
- `S:\services\pipecat\main.py`
- `S:\services\openclaw\main.py`
- `S:\services\eva-os\main.py`

### Runtime State
- `S:\state\pids\*.pid` - Process ID files
- `S:\logs\services\*.out.log` - Service stdout
- `S:\logs\services\*.err.log` - Service stderr

## Troubleshooting

### Services Won't Start

1. **Check Python availability**:
   ```powershell
   python --version
   ```

2. **Check ports are available**:
   ```powershell
   netstat -ano | findstr ":7000"  # Check port 7000
   ```

3. **View service logs**:
   ```powershell
   Get-Content S:\logs\services\api-gateway.out.log -Tail 50
   Get-Content S:\logs\services\api-gateway.err.log
   ```

### Port Already in Use

If a port is already bound:

```powershell
# Find process using port 7000
Get-NetTCPConnection -LocalPort 7000 | Get-Process

# Kill the process (replace 1234 with PID)
Stop-Process -Id 1234 -Force
```

### Service Not Responding

1. **Check process is running**:
   ```powershell
   Get-Process -Name python
   Get-Content S:\state\pids\api-gateway.pid
   ```

2. **Verify no import errors**:
   ```powershell
   python -m py_compile S:\services\api-gateway\main.py
   ```

3. **Test manually**:
   ```powershell
   cd S:\services\api-gateway
   python -m uvicorn main:app --host 127.0.0.1 --port 7000
   ```

### Health Checks Fail

Services take 2-5 seconds to start. If health checks fail:

1. Wait a few more seconds
2. Try manual health check: `iwr http://127.0.0.1:7000/healthz`
3. Check logs for startup errors

## Development Workflow

### Enable Auto-Reload

Use the `-Reload` flag for development:

```powershell
.\start-sonia-stack.ps1 -Reload
```

Services will restart automatically when you edit files.

### Testing an Endpoint

```powershell
# GET request
iwr http://127.0.0.1:7000/status | ConvertFrom-Json

# POST request
$body = @{text = "Hello"} | ConvertTo-Json
iwr -Uri http://127.0.0.1:7000/chat -Method Post -Body $body -ContentType application/json
```

### Viewing Live Logs

```powershell
# Follow API Gateway logs
Get-Content -Path S:\logs\services\api-gateway.out.log -Wait -Tail 20
```

### Custom Python Environment

To use a specific Python:

```powershell
# Set environment variable
$env:PYTHON_EXE = "C:\Python311\python.exe"

# Or in .env
# PYTHON_EXE=C:\Python311\python.exe
```

## Service Endpoints

### API Gateway (7000)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /status` - Detailed status
- `POST /chat` - Chat endpoint

### Model Router (7010)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /route?task_type=text` - Route to model
- `POST /select` - Select model by requirements

### Memory Engine (7020)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /status` - Detailed status
- `POST /recall` - Recall memories
- `POST /store` - Store memory
- `GET /search?q=...` - Vector search

### Pipecat (7030)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /status` - Detailed status
- `WebSocket /ws/voice` - Voice streaming
- `WebSocket /ws/events` - Event streaming
- `POST /asr` - Speech-to-text
- `POST /tts` - Text-to-speech

### OpenClaw (7040)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /status` - Detailed status
- `GET /tools` - List available tools
- `GET /tools/{tool_name}` - Get tool info
- `POST /execute` - Execute tool
- `POST /verify` - Verify execution
- `GET /audit/executions` - View audit log

### EVA-OS (7050)
- `GET /healthz` - Health check
- `GET /` - Status
- `GET /status` - Detailed status
- `GET /tasks` - List tasks
- `POST /tasks` - Create task
- `GET /approvals` - List approvals
- `POST /approve` - Approve action
- `GET /health/all` - Check all services

## Advanced Usage

### Custom Root Directory

Start from non-standard location:

```powershell
.\start-sonia-stack.ps1 -Root "D:\sonia"
```

### Skip Health Checks

For faster startup (not recommended):

```powershell
.\start-sonia-stack.ps1 -SkipHealthCheck
```

### Test Configuration Without Starting

```powershell
.\start-sonia-stack.ps1 -TestOnly
```

### Custom Timeout for Health Checks

```powershell
.\start-sonia-stack.ps1 -HealthCheckTimeoutSeconds 60
```

## Next Steps

1. **Run smoke tests** (when available):
   ```powershell
   .\tests\smoke\test-services.ps1
   ```

2. **Check memory engine health**:
   ```powershell
   .\scripts\diagnostics\doctor-sonia.ps1
   ```

3. **Review logs**:
   ```powershell
   Get-ChildItem S:\logs\services\*.out.log | ForEach-Object {
       Write-Host "`n=== $($_.Name) ===" ; Get-Content $_ -Tail 10
   }
   ```

## Architecture Notes

### Service Discovery
Services use hardcoded ports. In production, consider:
- Service registry (Consul, Eureka)
- Load balancer (HAProxy, Nginx)
- Container orchestration (Kubernetes, Docker Compose)

### State Management
Currently, all services are stateless. PID files serve as lifecycle markers.

### Logging
All services log to:
- stdout → `S:\logs\services\<service>.out.log`
- stderr → `S:\logs\services\<service>.err.log`

Configure in `S:\configs\logging.yaml`

### Health Monitoring
EVA-OS monitors all downstream services on port 7050.

## References

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Uvicorn**: https://www.uvicorn.org/
- **PowerShell Docs**: https://docs.microsoft.com/powershell/

## Support

For issues:
1. Check logs in `S:\logs\services\`
2. Review error analysis report: `S:\ERROR_ANALYSIS_REPORT.md`
3. Test services individually with `python -m uvicorn main:app`

---

**Build Version**: 1.0.0 Final Iteration  
**Last Updated**: 2026-02-08  
**Root**: S:\
