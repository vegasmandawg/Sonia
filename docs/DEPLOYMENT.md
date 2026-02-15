# DEPLOYMENT

Fresh install procedure for SONIA from git clone through first healthy stack.

## Prerequisites

### System Requirements
- **OS**: Windows 11 Pro 10.0.26200 or later
- **GPU**: NVIDIA GPU with 8GB+ VRAM recommended (4GB minimum)
- **RAM**: 16GB minimum, 32GB recommended
- **Disk**: 50GB free space on S:\ drive
- **Python**: 3.11 or 3.12
- **Node.js**: 20.x or later (for UI)
- **Git**: 2.40 or later

### External Dependencies
- **Ollama**: Required for local model inference (http://127.0.0.1:11434)
- **NVIDIA Driver**: Latest CUDA-capable driver for GPU support
- **Conda or Miniconda**: For Python environment management

## Environment Setup

### 1. Clone Repository
```powershell
# Clone to S:\ drive (canonical root)
cd S:\
git clone <repository-url> .
```

### 2. Create Python Environment
```powershell
# Create conda environment at S:\envs\sonia-core
conda create -p S:\envs\sonia-core python=3.11 -y
conda activate S:\envs\sonia-core

# Install dependencies
cd S:\services\api-gateway
pip install -r requirements.txt

cd S:\services\model-router
pip install -r requirements.txt

cd S:\services\memory-engine
pip install -r requirements.txt

cd S:\services\pipecat
pip install -r requirements.txt

cd S:\services\openclaw
pip install -r requirements.txt

cd S:\services\eva-os
pip install -r requirements.txt
```

### 3. Install Ollama Models
```powershell
# Install required models (check config\sonia-config.json for full list)
ollama pull sonia-vlm:32b
ollama pull qwen2.5:7b
ollama pull qwen3-vl:32b-instruct

# Verify models loaded
iwr http://127.0.0.1:11434/api/tags | ConvertFrom-Json
```

### 4. Create Required Directories
```powershell
mkdir S:\state\pids -Force
mkdir S:\logs\services -Force
mkdir S:\logs\gateway -Force
mkdir S:\data -Force
mkdir S:\backups\state -Force
mkdir S:\backups\db -Force
mkdir S:\incidents -Force
```

### 5. Initialize Database
```powershell
# Memory engine creates S:\data\memory.db on first start
# WAL mode enabled automatically
# Schema version: 9 migrations applied at boot
```

## Configuration

### 1. Review Config File
```powershell
# Canonical config: S:\config\sonia-config.json
# - Service ports: 7000-7070
# - Model routing profiles
# - Memory discipline settings
# - Privacy controls
```

### 2. Environment Variables (Optional)
```powershell
# Set if using non-standard paths
$env:SONIA_ROOT = "S:\"

# API keys for cloud models (optional, for Anthropic/OpenRouter)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:OPENROUTER_API_KEY = "sk-or-..."
```

### 3. Secrets Management
```powershell
# Never commit secrets to git
# Add to .gitignore:
# - .env files
# - config/*.local.json
# - state/
# - data/
# - backups/
```

## Service Startup Order

SONIA services must start in dependency order:

1. **API Gateway** (port 7000) - Front door, session management
2. **Model Router** (port 7010) - Provider selection, fallback logic
3. **Memory Engine** (port 7020) - Persistence, retrieval
4. **Pipecat** (port 7030) - Voice I/O, modality gateway
5. **OpenClaw** (port 7040) - Action executor, tool catalog
6. **EVA-OS** (port 7050) - Supervisory control plane

Optional services:
- **Vision Capture** (port 7060) - Camera capture, privacy gate
- **Perception** (port 7070) - VLM inference, scene analysis

### Automated Startup
```powershell
# Use canonical launcher
.\start-sonia-stack.ps1

# Options:
# -Reload           Enable auto-reload for development
# -SkipHealthCheck  Skip post-startup health verification
# -SkipPreflight    Skip environment validation
# -LaunchUI         Launch Electron UI after services ready
```

### Manual Startup (Individual Service)
```powershell
# Load library functions
. S:\scripts\lib\sonia-stack.ps1

# Start single service
Start-SoniaService -ServiceName "api-gateway" -ServiceDir "S:\services\api-gateway" -Port 7000

# Wait for health
Wait-SoniaServiceHealth -Port 7000 -MaxWaitSeconds 30
```

## Port Verification

### Check All Ports
```powershell
# List listening ports
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 7000,7010,7020,7030,7040,7050,7060,7070 }

# Check specific service
Test-NetConnection -ComputerName 127.0.0.1 -Port 7000
```

### Health Endpoints
All services expose `/healthz`:
```powershell
# API Gateway
iwr http://127.0.0.1:7000/healthz | ConvertFrom-Json

# Model Router
iwr http://127.0.0.1:7010/healthz | ConvertFrom-Json

# Memory Engine
iwr http://127.0.0.1:7020/healthz | ConvertFrom-Json

# Expected response:
# { "status": "ok", "service": "api-gateway", "version": "3.0.0", "uptime_seconds": 42 }
```

## Smoke Test Commands

### 1. Health Check All Services
```powershell
.\scripts\health-smoke.ps1
```

### 2. Test Turn Pipeline (Stage 2)
```powershell
.\scripts\smoke_turn.ps1

# Expected: 200 OK with turn_id, response text
```

### 3. Test Session Lifecycle (Stage 3)
```powershell
.\scripts\smoke_stage3_voice.ps1

# Expected: Session created, text turn processed, session deleted
```

### 4. Test Multimodal (Stage 4)
```powershell
.\scripts\smoke_stage4_multimodal.ps1

# Expected: Vision frame processed, quality controls applied
```

### 5. Test Action Pipeline (Stage 5)
```powershell
.\scripts\soak_stage5_actions.ps1 -Sessions 1 -ActionsPerSession 5

# Expected: Actions classified, confirmations minted, DLQ empty
```

### 6. Manual API Test
```powershell
# Create session
$session = iwr -Method POST http://127.0.0.1:7000/v1/sessions -ContentType "application/json" -Body '{"user_id":"test"}' | ConvertFrom-Json

# Send turn
$turn = iwr -Method POST http://127.0.0.1:7000/v1/turn -ContentType "application/json" -Body "{`"user_id`":`"test`",`"text`":`"Hello SONIA`"}" | ConvertFrom-Json

# Check memory
iwr "http://127.0.0.1:7020/v1/memory/search?query=hello&limit=5" | ConvertFrom-Json

# Delete session
iwr -Method DELETE "http://127.0.0.1:7000/v1/sessions/$($session.session_id)"
```

## Post-Deployment Verification

### 1. Check Logs
```powershell
# Service logs
Get-Content S:\logs\services\api-gateway.out.log -Tail 20

# Gateway JSONL logs (sessions, turns, tools, errors)
Get-Content S:\logs\gateway\sessions.jsonl -Tail 5
Get-Content S:\logs\gateway\turns.jsonl -Tail 5
Get-Content S:\logs\gateway\tools.jsonl -Tail 5
Get-Content S:\logs\gateway\errors.jsonl -Tail 5
```

### 2. Check Database
```powershell
# Verify memory.db exists and is writable
Test-Path S:\data\memory.db
Test-Path S:\data\memory.db-wal
Test-Path S:\data\memory.db-shm

# Check schema version (should be 9)
sqlite3 S:\data\memory.db "SELECT * FROM schema_version;"
```

### 3. Check PID Files
```powershell
# Verify all services have PID files
Get-ChildItem S:\state\pids\*.pid

# Expected: api-gateway.pid, model-router.pid, memory-engine.pid, pipecat.pid, openclaw.pid, eva-os.pid
```

### 4. GPU Verification
```powershell
# Check GPU availability
nvidia-smi --query-gpu=name,memory.total,memory.free,utilization.gpu --format=csv

# Expected: 4GB+ free VRAM, <50% utilization at idle
```

## Known Limitations / Non-Goals

1. **Single-Machine Only**: No distributed deployment or multi-node clustering.
2. **Windows-Only**: No official support for Linux or macOS (WSL untested).
3. **Local Network**: No internet exposure or external API access by default.
4. **No Docker**: Services run directly via Python, not containerized.
5. **Manual Backups**: No automated backup scheduling (use Task Scheduler separately).
6. **No Hot Reload**: Service restarts required for config changes.
7. **SQLite Limits**: Memory database limited to single-writer concurrency.
8. **GPU Required**: CPU-only mode untested and not recommended.
9. **No Multi-Tenancy**: Single-user system, no user isolation.
10. **Port Conflicts**: Manual resolution required if ports 7000-7070 already in use.

## Troubleshooting First Boot

### Service Won't Start
1. Check Python path: `Test-Path S:\envs\sonia-core\python.exe`
2. Check port conflicts: `Get-NetTCPConnection -LocalPort 7000 -State Listen`
3. Check logs: `Get-Content S:\logs\services\api-gateway.err.log`
4. Verify dependencies: `pip list | Select-String fastapi`

### Ollama Connection Failed
1. Check Ollama running: `iwr http://127.0.0.1:11434/api/tags`
2. Verify models loaded: `ollama list`
3. Check GPU availability: `nvidia-smi`
4. Restart Ollama: `Restart-Service Ollama` (if installed as service)

### Health Check Timeout
1. Wait longer: Services take 5-15s to boot
2. Check stderr: `Get-Content S:\logs\services\*.err.log`
3. Verify Python env active: `where.exe python` should show S:\envs\sonia-core\python.exe
4. Check firewall: Windows Firewall may block localhost on first run

### Database Errors
1. Check disk space: `Get-PSDrive S`
2. Verify write permissions: `Test-Path S:\data -PathType Container`
3. Delete corrupted DB: `Remove-Item S:\data\memory.db*` (data loss!)
4. Let memory-engine recreate on next boot

## Next Steps

1. Run promotion gate: `.\scripts\promotion-gate-v210.ps1` (all gates must pass)
2. Schedule daily backups (see BACKUP_RECOVERY.md)
3. Configure API keys for cloud models (optional)
4. Install UI: `cd ui\sonia-avatar; npm install; npm run build`
5. Review OPERATIONS_RUNBOOK.md for day-to-day procedures
