# Sonia Stack - Deployment & Operations Guide

**Date**: 2026-02-08  
**Version**: 1.0  
**Status**: Production Ready  

---

## Quick Start

### Minimum Requirements
- Windows 10+ or Linux
- Python 3.11+
- 4 GB RAM (8+ GB recommended)
- Internet connection for model downloads

### One-Command Start

```powershell
cd S:\
.\start-sonia-stack.ps1
```

This will:
1. Validate root directory and configuration
2. Start all 6 services (API Gateway, Model Router, Memory Engine, Pipecat, OpenClaw, EVA-OS)
3. Run health checks on all endpoints
4. Display status and logs

### Verify Services Are Running

```powershell
# Check if all services are healthy
curl http://localhost:7000/healthz  # API Gateway
curl http://localhost:7010/healthz  # Model Router
curl http://localhost:7020/healthz  # Memory Engine
curl http://localhost:7030/healthz  # Pipecat
curl http://localhost:7040/healthz  # OpenClaw
curl http://localhost:7050/healthz  # EVA-OS
```

All should return 200 OK with:
```json
{
  "ok": true,
  "service": "<service-name>",
  "timestamp": "2026-02-08T09:30:00.000Z"
}
```

### Graceful Shutdown

```powershell
.\stop-sonia-stack.ps1
```

---

## Architecture Overview

### Service Stack (6 Microservices)

```
┌─────────────────────────────────────────────────────────┐
│                    API Gateway (7000)                    │
│  - Orchestrates requests across all services             │
│  - Standard response envelopes                           │
│  - Correlation ID propagation                            │
└─────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
    │ Model  │    │ Memory │    │Pipecat │    │OpenClaw│
    │Router  │    │ Engine │    │ (Voice)│    │ (Tools)│
    │(7010)  │    │ (7020) │    │ (7030) │    │ (7040) │
    └────────┘    └────────┘    └────────┘    └────────┘
         │              │              │              │
         └──────────────┴──────────────┴──────────────┘
                        │
                        ▼
        ┌────────────────────────────────┐
        │   EVA-OS Control Plane (7050)   │
        │   - Tool approval gateway       │
        │   - Risk classification         │
        │   - Deterministic execution     │
        └────────────────────────────────┘
```

### Service Responsibilities

| Service | Port | Purpose | Key Features |
|---------|------|---------|--------------|
| API Gateway | 7000 | Request orchestration | Chat, action execution, dependency routing |
| Model Router | 7010 | LLM provider abstraction | Ollama, Anthropic, OpenRouter support |
| Memory Engine | 7020 | Semantic memory system | Hybrid search (vector + BM25), embeddings, decay |
| Pipecat | 7030 | Voice I/O & sessions | VAD, ASR, TTS, WebSocket streaming |
| OpenClaw | 7040 | Tool catalog & execution | 13 standard tools, policy enforcement |
| EVA-OS | 7050 | Control plane & approval | Risk classification, approval workflow |

---

## Configuration

### Main Configuration File
**Location**: `S:\config\sonia-config.json`

```json
{
  "services": {
    "api_gateway": {
      "port": 7000,
      "host": "127.0.0.1",
      "version": "1.0.0"
    },
    "model_router": {
      "port": 7010,
      "providers": {
        "ollama": { "base_url": "http://127.0.0.1:11434" },
        "anthropic": { "api_key": "required" },
        "openrouter": { "api_key": "required" }
      }
    },
    "memory_engine": {
      "port": 7020,
      "embeddings": {
        "provider": "ollama",
        "model": "nomic-embed-text"
      }
    },
    "pipecat": {
      "port": 7030
    },
    "openclaw": {
      "port": 7040
    },
    "eva_os": {
      "port": 7050
    }
  },
  "logging": {
    "level": "INFO",
    "format": "json"
  }
}
```

### Environment Variables

Before starting, set required API keys:

```powershell
# Anthropic API (optional, for Model Router)
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# OpenRouter API (optional, for Model Router)
$env:OPENROUTER_API_KEY = "sk-or-..."

# Ollama (optional, if using local LLM)
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
```

---

## Running Services Individually

### API Gateway
```powershell
cd S:\services\api-gateway
python -m uvicorn main:app --host 127.0.0.1 --port 7000 --reload
```

### Model Router
```powershell
cd S:\services\model-router
python -m uvicorn main:app --host 127.0.0.1 --port 7010 --reload
```

### Memory Engine
```powershell
cd S:\services\memory-engine
python -m uvicorn main:app --host 127.0.0.1 --port 7020 --reload
```

### Pipecat (Voice)
```powershell
cd S:\services\pipecat
python -m uvicorn main:app --host 127.0.0.1 --port 7030 --reload
```

### OpenClaw (Tools)
```powershell
cd S:\services\openclaw
python -m uvicorn main:app --host 127.0.0.1 --port 7040 --reload
```

### EVA-OS (Control Plane)
```powershell
cd S:\services\eva-os
python -m uvicorn main:app --host 127.0.0.1 --port 7050 --reload
```

---

## Testing the System

### 1. Health Check All Services
```powershell
# Use the dependency check endpoint
curl -X GET http://localhost:7000/v1/deps
```

Response shows health of all downstream services:
```json
{
  "ok": true,
  "service": "api-gateway",
  "operation": "deps",
  "data": {
    "memory_engine": {"status": "ok", "duration_ms": 45},
    "model_router": {"status": "ok", "duration_ms": 52},
    "openclaw": {"status": "ok", "duration_ms": 38},
    "pipecat": {"status": "ok", "duration_ms": 41}
  }
}
```

### 2. Test Chat Endpoint
```powershell
$body = @{
    text = "What is the capital of France?"
} | ConvertTo-Json

curl -X POST http://localhost:7000/v1/chat `
  -ContentType "application/json" `
  -Body $body
```

### 3. Test Tool Execution
```powershell
$body = @{
    tool_name = "shell.run"
    args = @{
        command = "Get-ChildItem"
    }
} | ConvertTo-Json

curl -X POST http://localhost:7000/v1/action `
  -ContentType "application/json" `
  -Body $body
```

### 4. Test Voice Session (WebSocket)
```powershell
# Create session
$sessionResp = curl -X POST http://localhost:7030/session/start

$sessionId = ($sessionResp | ConvertFrom-Json).data.session_id

# Connect to WebSocket
$ws = New-WebSocket -Uri "ws://localhost:7030/ws/$sessionId"

# Send message event
$event = @{
    type = "MESSAGE"
    data = @{ text = "Hello, how are you?" }
} | ConvertTo-Json

$ws.Send($event)

# Listen for response
$response = $ws.Receive()
Write-Host $response
```

### 5. Run Integration Tests
```powershell
cd S:\tests\integration
python -m pytest test_phase2_e2e.py -v
```

### 6. Run Smoke Tests
```powershell
cd S:\scripts\smoke
.\phase2-smoke.ps1
```

---

## Monitoring & Diagnostics

### Health Check Script
```powershell
.\scripts\diagnostics\doctor-sonia.ps1
```

This performs:
1. **Foundational**: Python, directories, configuration
2. **Dependencies**: Required packages
3. **Services**: Port availability, connectivity
4. **Upstream**: LLM providers, model availability
5. **Logs**: Log file accessibility
6. **System**: Disk space, memory

### View Logs

**API Gateway logs**:
```powershell
Get-Content S:\logs\services\api-gateway.log -Tail 100
```

**Memory Engine logs**:
```powershell
Get-Content S:\logs\services\memory-engine.log -Tail 100
```

**All service logs**:
```powershell
Get-ChildItem S:\logs\services\*.log | ForEach-Object { 
    Write-Host "=== $($_.Name) ===" 
    Get-Content $_.FullName -Tail 20
}
```

### Real-Time Monitoring
```powershell
# Watch service health continuously
while($true) {
    Clear-Host
    curl -s http://localhost:7000/v1/deps | ConvertFrom-Json | ConvertTo-Json -Depth 10
    Start-Sleep -Seconds 5
}
```

---

## Troubleshooting

### Service Won't Start

**Symptom**: "Port already in use"

**Solution**:
```powershell
# Find process on port
netstat -ano | findstr :7000

# Kill process (replace PID)
taskkill /PID 12345 /F
```

**Symptom**: "Module not found"

**Solution**:
```powershell
# Install requirements
cd S:\services\api-gateway
pip install -r requirements.lock
```

### Service Health Check Fails

**Symptom**: `/healthz` returns 500 error

**Solution**:
1. Check logs: `Get-Content S:\logs\services\api-gateway.log -Tail 50`
2. Verify downstream services are running
3. Check port availability: `netstat -ano | findstr :7000`
4. Restart service

### Slow Performance

**Symptom**: Requests taking >5 seconds

**Solution**:
1. Check memory usage: `Get-Process | Where-Object {$_.ProcessName -like "python*"}`
2. Check disk space: `Get-Volume`
3. Check CPU: `Get-Process | Sort-Object CPU -Descending | Select -First 10`
4. Review logs for errors or slow queries

### Voice Not Working

**Symptom**: WebSocket connection fails or VAD not detecting speech

**Solution**:
1. Check audio device: `Get-AudioDevice`
2. Check Pipecat service: `curl http://localhost:7030/healthz`
3. Check logs: `Get-Content S:\logs\services\pipecat.log -Tail 50`
4. Verify VAD configuration in `S:\services\pipecat\pipeline\vad.py`

---

## Performance Tuning

### Increase Memory Engine Search Speed
```json
{
  "memory_engine": {
    "search": {
      "batch_size": 64,
      "hnsw_ef": 200,
      "bm25_k1": 1.5,
      "bm25_b": 0.75
    }
  }
}
```

### Increase Voice Processing Speed
```json
{
  "pipecat": {
    "voice": {
      "vad_threshold": 0.5,
      "sample_rate": 16000,
      "chunk_size": 512
    }
  }
}
```

### Enable Request Caching
```json
{
  "api_gateway": {
    "caching": {
      "enabled": true,
      "ttl_seconds": 300,
      "max_size_mb": 100
    }
  }
}
```

---

## Backup & Recovery

### Backup Data
```powershell
# Backup memory database
Copy-Item S:\data\memory\* S:\backups\daily\ -Recurse -Force

# Backup sessions
Copy-Item S:\data\sessions\* S:\backups\daily\ -Recurse -Force

# Backup configuration
Copy-Item S:\config\* S:\backups\daily\ -Recurse -Force
```

### Restore from Backup
```powershell
# Stop services
.\stop-sonia-stack.ps1

# Restore files
Copy-Item S:\backups\daily\* S:\data\ -Recurse -Force
Copy-Item S:\backups\daily\*.json S:\config\ -Force

# Restart services
.\start-sonia-stack.ps1
```

---

## Security Hardening

### Enable Authentication
Add to API Gateway main.py:
```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/v1/chat")
async def chat(request: ChatRequest, credentials: HTTPAuthCredentials = Depends(security)):
    # Validate token
    pass
```

### Enable HTTPS
```python
import ssl
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain("cert.pem", "key.pem")

uvicorn.run(app, ssl_context=ssl_context)
```

### Rate Limiting
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/v1/chat")
@limiter.limit("10/minute")
async def chat(request: ChatRequest):
    pass
```

---

## Production Deployment

### Systemd Service (Linux)
Create `/etc/systemd/system/sonia.service`:
```ini
[Unit]
Description=Sonia Stack
After=network.target

[Service]
Type=forking
ExecStart=/opt/sonia/start-sonia-stack.ps1
ExecStop=/opt/sonia/stop-sonia-stack.ps1
User=sonia

[Install]
WantedBy=multi-user.target
```

### Docker Deployment
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY services /app/services
COPY config /app/config
COPY shared /app/shared

RUN pip install -r services/api-gateway/requirements.lock

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7000"]
```

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sonia-api-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sonia-api-gateway
  template:
    metadata:
      labels:
        app: sonia-api-gateway
    spec:
      containers:
      - name: api-gateway
        image: sonia:api-gateway
        ports:
        - containerPort: 7000
        env:
        - name: MEMORY_ENGINE_URL
          value: "http://sonia-memory:7020"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 7000
          initialDelaySeconds: 30
          periodSeconds: 10
```

---

## Support & Resources

### Documentation
- **Architecture**: S:\ARCHITECTURE.md
- **Boot Contract**: S:\BOOT_CONTRACT.md
- **Runtime Contract**: S:\RUNTIME_CONTRACT.md
- **Phase Reports**: S:\PHASE_*_COMPLETION_REPORT.md

### API Specifications
- **Memory Engine**: S:\docs\MEMORY_ENGINE_API.md
- **Pipecat Voice**: S:\docs\PIPECAT_VOICE_API.md
- **Vision Streaming**: S:\services\api-gateway\VISION_STREAMING_API.md

### Tools & Scripts
- **Health Diagnostic**: S:\scripts\diagnostics\doctor-sonia.ps1
- **Integration Tests**: S:\tests\integration\test_phase2_e2e.py
- **Smoke Tests**: S:\scripts\smoke\phase2-smoke.ps1

---

**Last Updated**: 2026-02-08  
**Version**: 1.0  
**Status**: Production Ready  
