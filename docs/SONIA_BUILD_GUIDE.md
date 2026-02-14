# SONIA Build Guide - Final Iteration

**Status:** 🔨 Under Construction  
**Version:** 1.0.0-alpha  
**Date:** 2026-02-08  
**Root:** `S:\`

---

## Overview

Sonia is a **companion-grade AI assistant** built as a modular service stack on Windows. This guide walks you through the complete build process from raw upstream sources to a running system.

**What You're Building:**
- 5-service FastAPI stack (7000-7050 ports)
- EVA-OS: Supervisory control plane
- Pipecat: Real-time voice modality
- OpenClaw: Safe action execution
- Memory Engine: Persistent knowledge
- Model Router: LLM provider abstraction

---

## Prerequisites

### Hardware
- Windows 11 or later
- 16 GB RAM minimum (32 GB recommended for local LLMs)
- 100 GB free disk space
- Optional: GPU (NVIDIA recommended for local inference)

### Software
- **Node.js 20+** (get from https://nodejs.org/)
- **Python 3.11+** (or Miniconda from S:\tools\sysprog\)
- **npm or pnpm** (included with Node.js)
- **Git** (optional, for version tracking)

### Upstream Sources (Already Available)
All necessary upstream packages are in `S:\tools\sysprog\`:
- `LM-Studio-0.4.2-2-x64.exe` — GUI for local LLM
- `Miniconda3-py311_25.11.1-1-Windows-x86_64.exe` — Python environment
- `openclaw-main.zip` — Upstream OpenClaw
- `pipecat-main.zip` — Upstream Pipecat
- `pipecat-flows-main.zip` — Optional Pipecat framework
- `vllm-main.zip` — Optional GPU-accelerated LLM
- `EVA-OS-main.zip` — Reference EVA-OS (we built our own)

---

## Build Phases

### Phase 0: Environment Setup

**1. Install Node.js**
```powershell
# Download from https://nodejs.org/ (v20+ LTS)
# Run installer, add to PATH, verify:
node --version    # Should show v20.x.x or later
npm --version     # Should show 10.x.x or later
```

**2. Install Python/Miniconda**
```powershell
# Run: S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe
# During install:
#   ☑ Add to PATH
#   ☑ Register as default Python
# Verify:
python --version  # Should show Python 3.11+
conda --version   # Should show conda 25.x
```

**3. Install LM-Studio (Optional for Local LLM)**
```powershell
# Run: S:\tools\sysprog\LM-Studio-0.4.2-2-x64.exe
# GUI installer; choose: S:\tools\lm-studio
# LM-Studio runs on port 1234 for local inference
```

---

### Phase 1: Extract Upstream Sources

**Command:**
```powershell
.\scripts\ops\setup-upstream-dependencies.ps1
```

**What it does:**
- Extracts OpenClaw, Pipecat, vLLM to `S:\integrations\`
- Creates `CURRENT.txt` pointers for version tracking
- Validates extraction integrity
- Sets up folder structure

**After extraction:**
```
S:\integrations\
├─ openclaw\
│  └─ upstream\
│     └─ CURRENT.txt → points to extracted repo root
├─ pipecat\
│  └─ upstream\
│     └─ CURRENT.txt → points to extracted repo root
└─ (others...)
```

---

### Phase 2: Initialize Sonia Directories and Config

**Already done by the setup scripts:**
```
S:\
├─ config\
│  └─ sonia-config.json          ← Master configuration
├─ shared\
│  └─ schemas\
│     └─ envelopes.json          ← Message contracts
├─ services\
│  ├─ eva-os\                    ← Supervisory control plane
│  ├─ openclaw\
│  │  └─ tool_catalog.json       ← Safe action definitions
│  ├─ memory-engine\
│  ├─ pipecat\
│  └─ model-router\
├─ logs\
│  └─ services\                  ← All service logs live here
├─ state\
│  └─ pids\                      ← PID tracking
└─ scripts\
   ├─ ops\
   │  ├─ start-sonia-stack.ps1   ← Main launcher
   │  └─ setup-upstream-dependencies.ps1
   └─ diagnostics\
      └─ doctor-sonia.ps1        ← Health check
```

---

### Phase 3: Health Check

**Command:**
```powershell
.\scripts\diagnostics\doctor-sonia.ps1
```

**What it validates:**
- ✓ Root directory structure
- ✓ Configuration files present
- ✓ EVA-OS module ready
- ✓ OpenClaw tool catalog loaded
- ✓ Node.js and Python available
- ✓ Conda/Miniconda available
- ✓ Ports 7000-7050 available
- ✓ Upstream sources extracted

**If all checks pass:** Ready to start the stack!

---

### Phase 4: Start the Stack

**Command:**
```powershell
.\start-sonia-stack.ps1
```

**What it does:**
1. Validates configuration and ports
2. Creates log and PID directories
3. Starts 5 services (7000-7040)
4. Performs health checks
5. Reports readiness

**Services Started:**
| Service | Port | Purpose |
|---------|------|---------|
| API Gateway | 7000 | Stable front door, UI transport |
| Model Router | 7010 | LLM provider selection |
| Memory Engine | 7020 | Persistent knowledge/ledger |
| Pipecat | 7030 | Real-time voice I/O |
| OpenClaw | 7040 | Safe action execution |

**Verify Services:**
```powershell
# Check logs
Get-Content -Wait -Tail 50 S:\logs\services\api-gateway.out.log

# Check health
Invoke-WebRequest http://127.0.0.1:7000/healthz
Invoke-WebRequest http://127.0.0.1:7010/healthz
# ... etc for all 5 services
```

---

## Architecture Overview

### Core Loop
```
PERCEIVE (Pipecat/Voice) 
    ↓
INTERPRET (EVA-OS/Model Router)
    ↓
DECIDE (EVA-OS policy)
    ↓
ACT (OpenClaw/Execute)
    ↓
VERIFY (Check results)
    ↓
REMEMBER (Memory Engine)
```

### Service Responsibilities

**API Gateway (7000)**
- HTTP/WebSocket endpoint for UI
- Input normalization
- Output delivery
- Streams responses

**EVA-OS (Supervisor)**
- Orchestration of the loop
- Policy gating & approval tokens
- Task state management
- Service health monitoring
- Graceful degradation

**Pipecat (7030)**
- Mic input → ASR → transcript
- Text → TTS → speaker output
- Voice activity detection (VAD)
- Turn-taking, barge-in
- Streaming events

**Model Router (7010)**
- Select best LLM by constraints
- Route to local or cloud models
- Fallback policies
- Latency optimization

**Memory Engine (7020)**
- Persistent ledger (facts, preferences, project state)
- Knowledge workspace (document ingestion, retrieval)
- Structured memory discipline
- Provenance tracking

**OpenClaw (7040)**
- Tool catalog: filesystem, process, shell operations
- Risk-tiered execution (Tier 0-3)
- Approval enforcement
- Verification-first approach
- Logs to S:\logs\tools\

---

## Message Contracts (Phase A: Complete)

All messages follow **canonical envelopes** defined in `S:\shared\schemas\envelopes.json`:

```json
{
  "UserTurn": {
    "id": "turn-001",
    "timestamp": "2026-02-08T14:30:00Z",
    "mode": "conversation",
    "text": "user's input",
    "confidence": 1.0,
    "input_type": "text|voice|vision"
  },
  
  "ToolCall": {
    "id": "tool-001",
    "tool_name": "filesystem.write_file",
    "args": {"path": "S:\\...", "content": "..."},
    "approval_required": true,
    "approval_token": "token-xyz"
  },
  
  "ToolResult": {
    "id": "result-001",
    "tool_call_id": "tool-001",
    "status": "success|failed|blocked",
    "artifacts": [...],
    "verification_results": {...}
  }
}
```

---

## Configuration Reference

**Master config:** `S:\config\sonia-config.json`

Key sections:
- `services`: Port definitions, log locations
- `eva_os`: Default mode, approval timeout, degradation behavior
- `pipecat`: Audio rates, VAD settings, barge-in toggle
- `memory_engine`: Ledger path, knowledge workspace location
- `openclaw`: Tool catalog, root contract, approval rules
- `operational`: Health check intervals, log rotation

---

## EVA-OS Details (Phase B: Complete)

**Files:**
- `S:\services\eva-os\eva_os.py` — Core logic
- `S:\services\eva-os\eva_os_service.py` — FastAPI wrapper

**Responsibilities:**
1. **Orchestration**: Process user turns → decide → execute → verify
2. **Policy gating**: Classify tool calls by risk; issue approval tokens
3. **State management**: Track mode, task state, interaction state
4. **Service health**: Monitor service status, update capabilities
5. **Degradation**: If OpenClaw down → no execution; if Memory down → no recall

**Modes:**
| Mode | Behavior |
|------|----------|
| `conversation` | Propose, ask permission (default) |
| `operator` | Execute tasks, ask for destructive ops |
| `diagnostic` | Health checks, logs, observability |
| `dictation` | Capture only, no tool calls |
| `build` | Complete artifacts, pinned versions |

---

## OpenClaw Tool Catalog (Phase C: Complete)

**File:** `S:\services\openclaw\tool_catalog.json`

**Tiers:**
- **TIER_0_READONLY**: list, read, stat, query (no approval needed)
- **TIER_1_LOW_RISK**: create file/dir, append (ask in conversation mode)
- **TIER_2_MEDIUM_RISK**: move, copy, start process (ask in conversation/diagnostic)
- **TIER_3_DESTRUCTIVE**: delete, kill, arbitrary shell (always require approval)

**Tool Examples:**
```json
{
  "filesystem.write_file": {
    "tier": "TIER_1_LOW_RISK",
    "schema": {"path": "string", "content": "string"},
    "side_effects": ["creates_file", "modifies_file"],
    "verification_spec": {
      "type": "file_write",
      "check_exists": true,
      "return_hash": true
    }
  }
}
```

---

## Next Steps (After Build)

### Immediate
1. ✅ Run diagnostic: `.\scripts\diagnostics\doctor-sonia.ps1`
2. ✅ Start stack: `.\start-sonia-stack.ps1`
3. ✅ Verify services healthy: All `/healthz` endpoints return 200

### Short Term (Phase D-F)
- **Phase D:** Memory Engine minimal ledger + retrieval endpoint
- **Phase E:** Pipecat voice events (turn-finalization → barge-in → streaming TTS)
- **Phase F:** Expand UI automation, implement full streaming

### Medium Term
- UI/dashboard integration
- Voice command training
- Tool catalog expansion
- Knowledge base ingestion
- Performance tuning

---

## Troubleshooting

### "Port 7000 in use"
```powershell
# Find process using port
netstat -ano | findstr :7000
# Kill process
taskkill /PID <PID> /F
```

### "Service not responding after start"
```powershell
# Check logs
Get-Content S:\logs\services\api-gateway.out.log
Get-Content S:\logs\services\api-gateway.err.log
# Increase health check timeout
.\start-sonia-stack.ps1 -HealthCheckTimeoutSeconds 60
```

### "Python/Node.js not found"
```powershell
# Install from upstream
# Node: https://nodejs.org/
# Python: S:\tools\sysprog\Miniconda3-*.exe
# Then add to PATH and verify
node --version
python --version
```

### "Upstream extraction failed"
```powershell
# Try with -Force flag
.\scripts\ops\setup-upstream-dependencies.ps1 -Force
# Check disk space
[System.Math]::Round((Get-PSDrive S).Free / 1GB, 2)
```

---

## Project Structure

```
S:\
├─ config/                      # Configuration files
├─ shared/
│  └─ schemas/                  # JSON Schema contracts
├─ services/                    # Microservices
│  ├─ eva-os/                   # Supervisor (yours)
│  ├─ openclaw/                 # Action executor
│  ├─ memory-engine/            # Persistence
│  ├─ pipecat/                  # Voice I/O
│  └─ model-router/             # LLM routing
├─ integrations/                # Upstream sources
│  ├─ openclaw/
│  ├─ pipecat/
│  └─ (others...)
├─ scripts/
│  ├─ ops/                      # Operational scripts
│  └─ diagnostics/              # Health checks
├─ logs/
│  └─ services/                 # Service logs
├─ state/
│  └─ pids/                     # Process ID tracking
├─ docs/                        # Documentation
└─ tools/
   └─ sysprog/                  # Upstream tools (installers)
```

---

## References

- **Purpose & Scope:** `S:\docs\SONIA_ABOUT_COMBINED.pdf` (Document 1/5)
- **System Architecture:** `S:\docs\SONIA_ABOUT_COMBINED.pdf` (Document 2/5)
- **EVA-OS Details:** `S:\docs\SONIA_ABOUT_COMBINED.pdf` (Document 3/5)
- **Pipecat Voice:** `S:\docs\SONIA_ABOUT_COMBINED.pdf` (Document 4/5)
- **OpenClaw Actions:** `S:\docs\SONIA_ABOUT_COMBINED.pdf` (Document 5/5)

---

## Summary

You now have:
- ✅ **Phase A:** Canonical message envelopes (JSON schemas)
- ✅ **Phase B:** EVA-OS supervisory module with FastAPI wrapper
- ✅ **Phase C:** OpenClaw tool catalog with risk tiers
- 🔨 **Phase D:** Memory Engine (ready to implement)
- 🔨 **Phase E:** Pipecat voice events (ready to implement)
- 🔨 **Phase F:** UI automation and streaming (ready to implement)

**The chassis is complete. Everything else bolts on.**

Next: Extract upstream sources, verify health, start the stack, and iterate on phases D-F.

---

**Built on:** 2026-02-08  
**Iteration:** Final (1.0.0-alpha)  
**Root:** S:\
