# Sonia Stack - Quick Reference Guide

**Version**: 1.0  
**Last Updated**: 2026-02-08  

---

## Service Ports Quick Lookup

| Port | Service | Status Endpoint | Entry Point |
|------|---------|-----------------|-------------|
| 7000 | API Gateway | `/healthz` | `S:\services\api-gateway\main.py` |
| 7010 | Model Router | `/healthz` | `S:\services\model-router\main.py` |
| 7020 | Memory Engine | `/healthz` | `S:\services\memory-engine\main.py` |
| 7030 | Pipecat (Voice) | `/healthz` | `S:\services\pipecat\main.py` |
| 7040 | OpenClaw (Tools) | `/healthz` | `S:\services\openclaw\main.py` |
| 7050 | EVA-OS (Control) | `/healthz` | `S:\services\eva-os\main.py` |

---

## Essential Commands

### Start/Stop Stack
```powershell
# Start all services
.\start-sonia-stack.ps1

# Start with auto-reload (development)
.\start-sonia-stack.ps1 -Reload

# Stop all services
.\stop-sonia-stack.ps1

# Diagnostic checks
.\scripts\diagnostics\doctor-sonia.ps1
```

### Health Checks
```powershell
# Quick health check
curl http://localhost:7000/healthz

# Full dependency check
curl http://localhost:7000/v1/deps

# Watch health continuously
while($true) { cls; curl -s http://localhost:7000/v1/deps | ConvertFrom-Json | ConvertTo-Json; sleep 5 }
```

### View Logs
```powershell
# Last 50 lines of API Gateway
Get-Content S:\logs\services\api-gateway.log -Tail 50

# Stream logs in real-time
Get-Content S:\logs\services\api-gateway.log -Wait -Tail 20

# All service logs
Get-ChildItem S:\logs\services\*.log | ForEach-Object { Write-Host "`n=== $($_.Name) ==="; Get-Content $_.FullName -Tail 10 }
```

### Run Tests
```powershell
# Integration tests
cd S:\tests\integration
python -m pytest test_phase2_e2e.py -v

# Specific test
python -m pytest test_phase2_e2e.py::TestAPIGatewayChat -v

# Smoke tests
.\scripts\smoke\phase2-smoke.ps1
```

---

## Common Curl Examples

### Chat Request
```bash
curl -X POST http://localhost:7000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "text": "What is machine learning?"
  }'
```

### Tool Execution
```bash
curl -X POST http://localhost:7000/v1/action \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "shell.run",
    "args": {
      "command": "Get-ChildItem"
    }
  }'
```

### Memory Search
```bash
curl -X POST http://localhost:7020/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning basics",
    "limit": 10
  }'
```

### Store Memory
```bash
curl -X POST http://localhost:7020/store \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Python is a programming language",
    "type": "knowledge",
    "metadata": {
      "source": "tutorial"
    }
  }'
```

### Create Voice Session
```bash
curl -X POST http://localhost:7030/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "metadata": {
      "device": "microphone"
    }
  }'
```

---

## File Locations Cheat Sheet

### Configuration
- Main config: `S:\config\sonia-config.json`
- Environment config: `S:\config\env\`
- Service configs: `S:\config\services\*.yaml`

### Services
- API Gateway: `S:\services\api-gateway\`
- Model Router: `S:\services\model-router\`
- Memory Engine: `S:\services\memory-engine\`
- Pipecat: `S:\services\pipecat\`
- OpenClaw: `S:\services\openclaw\`
- EVA-OS: `S:\services\eva-os\`

### Data & Logs
- Data directory: `S:\data\`
- Memory data: `S:\data\memory\`
- Sessions: `S:\data\sessions\`
- Logs: `S:\logs\services\`

### Documentation
- Boot contract: `S:\BOOT_CONTRACT.md`
- Runtime contract: `S:\RUNTIME_CONTRACT.md`
- Deployment guide: `S:\DEPLOYMENT_GUIDE.md`
- Phase reports: `S:\PHASE_*_COMPLETION_REPORT.md`

### Tests
- Integration tests: `S:\tests\integration\`
- Unit tests: `S:\tests\unit\`
- Smoke tests: `S:\scripts\smoke\`

---

## Common Issues & Quick Fixes

### "Port already in use"
```powershell
# Find process
netstat -ano | findstr :7000

# Kill process
taskkill /PID 12345 /F
```

### "Module not found"
```powershell
cd S:\services\api-gateway
pip install -r requirements.lock
```

### "Service not responding"
```powershell
# Check logs
Get-Content S:\logs\services\api-gateway.log -Tail 50

# Restart service
.\stop-sonia-stack.ps1
# Wait 5 seconds
Start-Sleep -Seconds 5
.\start-sonia-stack.ps1
```

### "Database locked"
```powershell
# Stop services
.\stop-sonia-stack.ps1

# Remove lock files
Remove-Item S:\data\memory\*.lock -Force

# Restart
.\start-sonia-stack.ps1
```

### "Connection refused"
```powershell
# Verify service is running
Get-Process | Where-Object {$_.ProcessName -like "*python*"}

# Check ports
netstat -ano | findstr :7020

# Check health
curl http://localhost:7020/healthz
```

---

## Development Workflow

### Running Individual Service in Dev Mode
```powershell
# Terminal 1: API Gateway
cd S:\services\api-gateway
python -m uvicorn main:app --host 127.0.0.1 --port 7000 --reload

# Terminal 2: Memory Engine  
cd S:\services\memory-engine
python -m uvicorn main:app --host 127.0.0.1 --port 7020 --reload

# Terminal 3: Model Router
cd S:\services\model-router
python -m uvicorn main:app --host 127.0.0.1 --port 7010 --reload
```

### Modifying a Service
1. Stop that service with `Ctrl+C`
2. Make code changes
3. Service auto-reloads (if using `--reload`)
4. Verify with health check: `curl http://localhost:7000/v1/deps`

### Adding a New Tool to OpenClaw
1. Edit `S:\services\openclaw\registry.py` - add tool definition
2. Edit `S:\services\openclaw\executors\` - add executor if needed
3. Run tests: `cd S:\services\openclaw && python -m pytest -v`
4. Verify with: `curl http://localhost:7040/tools`

### Adding a New Memory Search Feature
1. Edit `S:\services\memory-engine\core\retriever.py`
2. Run tests: `cd S:\services\memory-engine && python -m pytest -v`
3. Test endpoint: `curl -X POST http://localhost:7020/search -H "Content-Type: application/json" -d '{...}'`

---

## Environment Variables

### Optional API Keys
```powershell
# Anthropic Claude
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# OpenRouter
$env:OPENROUTER_API_KEY = "sk-or-..."

# Custom Ollama URL
$env:OLLAMA_BASE_URL = "http://custom:11434"
```

### Service Configuration
```powershell
# Memory Engine embeddings model
$env:EMBEDDINGS_MODEL = "nomic-embed-text"

# Log level
$env:LOG_LEVEL = "DEBUG"  # or INFO, WARNING, ERROR

# Enable debug mode
$env:DEBUG = "1"
```

---

## Performance Metrics

### Expected Latencies
- **Chat request**: 500ms - 5s (depends on model)
- **Tool execution**: 100ms - 5s (depends on tool)
- **Memory search**: 50-200ms
- **Voice round-trip**: <1s (with sub-200ms network latency)
- **Health check**: <100ms

### Resource Usage (at rest)
- **Memory**: 500-800MB per service
- **CPU**: <5% per service
- **Disk**: 5-10GB total (models + data)

### Throughput (estimated)
- **Chat requests**: 10-50/sec (depends on model)
- **Memory searches**: 100-500/sec
- **Tool executions**: 10-100/sec
- **Voice sessions**: 10-50 concurrent

---

## API Response Format (Standard Envelope)

All endpoints return:
```json
{
  "ok": true/false,
  "service": "service-name",
  "operation": "operation-name",
  "correlation_id": "req_abc123...",
  "duration_ms": 245.5,
  "data": {
    "/* response data */": "here"
  },
  "error": null  // or {code, message, details}
}
```

Example error response:
```json
{
  "ok": false,
  "service": "api-gateway",
  "operation": "chat",
  "correlation_id": "req_abc123...",
  "duration_ms": 125.3,
  "data": null,
  "error": {
    "code": "TIMEOUT",
    "message": "Model Router did not respond within 30 seconds",
    "details": {
      "service": "model-router",
      "port": 7010
    }
  }
}
```

---

## Tool Registry (OpenClaw)

**Available Tools** (13 total):
1. `shell.run` - Execute shell commands
2. `file.read` - Read file contents
3. `file.write` - Write to files
4. `file.delete` - Delete files
5. `browser.open` - Open URL in browser
6. `browser.take_screenshot` - Capture screenshot
7. `browser.click` - Click element
8. `browser.type` - Type text
9. `memory.store` - Store in memory
10. `memory.recall` - Retrieve from memory
11. `memory.search` - Search memory
12. `approval.request` - Request approval (EVA-OS)
13. `approval.respond` - Respond to approval

**Tool Risk Tiers**:
- **TIER_0_READONLY**: Read-only operations (safe)
- **TIER_1_AWARENESS**: Operations with side-effects (requires logging)
- **TIER_2_APPROVAL**: High-risk operations (requires approval)
- **TIER_3_DESTRUCTIVE**: Destructive operations (requires explicit approval)

---

## Monitoring Dashboard (Manual)

Create a monitoring script in PowerShell:
```powershell
function Show-SoniaStatus {
    param([int]$RefreshSeconds = 5)
    
    while($true) {
        Clear-Host
        Write-Host "Sonia Status Dashboard" -ForegroundColor Cyan
        
        $deps = curl -s http://localhost:7000/v1/deps | ConvertFrom-Json
        
        foreach($key in $deps.data.PSObject.Properties.Name) {
            $service = $deps.data.$key
            $color = if($service.status -eq "ok") { "Green" } else { "Red" }
            Write-Host "$key`t $($service.status)`t $($service.duration_ms)ms" -ForegroundColor $color
        }
        
        Write-Host "`nRefresh in $RefreshSeconds seconds..."
        Start-Sleep -Seconds $RefreshSeconds
    }
}

Show-SoniaStatus
```

---

## Shutdown Checklist

Before shutdown, verify:
- [ ] No active chat/tool operations
- [ ] Voice sessions closed
- [ ] Memory saved
- [ ] Logs backed up (if needed)
- [ ] Configuration backed up (if modified)

Shutdown command:
```powershell
.\stop-sonia-stack.ps1
```

---

## Useful Documentation Links

- **Boot Contract**: `S:\BOOT_CONTRACT.md` - Service specs
- **Runtime Contract**: `S:\RUNTIME_CONTRACT.md` - SLAs
- **Deployment Guide**: `S:\DEPLOYMENT_GUIDE.md` - Full setup
- **Architecture**: `S:\ARCHITECTURE.md` - System design
- **Phase Reports**: `S:\PHASE_*_COMPLETION_REPORT.md` - Implementation details
- **API Docs**: `S:\docs\MEMORY_ENGINE_API.md` - Endpoint specs
- **Voice API**: `S:\docs\PIPECAT_VOICE_API.md` - Voice specifics

---

**Version**: 1.0  
**Last Updated**: 2026-02-08  
**Status**: Production Ready  
