# Sonia Stack

**Version**: v3.3.0-dev (In Development)
**Date**: 2026-02-15
**Branch**: `master` (merged from v3.3-dev)

---

## Overview

Sonia is a local-first AI assistant stack built as a microservices architecture with 8 services covering voice interaction, memory management, model routing, desktop automation, and visual perception.

## Services

| Service | Port | Status | Purpose |
|---------|------|--------|---------|
| API Gateway | 7000 | Active | Request orchestration, sessions, streaming, action pipeline |
| Model Router | 7010 | Active | LLM provider routing, profile-based selection |
| Memory Engine | 7020 | Active | Persistent memory ledger (SQLite), search |
| Pipecat | 7030 | Active | Voice I/O, WebSocket sessions, turn routing |
| OpenClaw | 7040 | Active | Tool execution, 13-capability registry |
| EVA-OS | 7050 | Active | Supervisory control, action safety gate |
| Vision Capture | 7060 | Foundation | Camera capture, ring buffer, privacy controls |
| Perception | 7070 | Foundation | Event-driven VLM inference, scene analysis |

## Quick Start

```powershell
# Start all services
S:\start-sonia-stack.ps1

# Stop all services
S:\stop-sonia-stack.ps1

# Health check
Invoke-WebRequest http://127.0.0.1:7000/healthz
```

## Architecture

- **Python env**: `S:\envs\sonia-core\python.exe` (Python 3.11, conda prefix)
- **Config**: `S:\config\sonia-config.json` (canonical)
- **Shared lib**: `S:\scripts\lib\sonia-stack.ps1`
- **Logs**: `S:\logs\services\`
- **PID files**: `S:\state\pids\`
- **Health endpoint**: `/healthz` on all services

## Key Capabilities

- **Turn Pipeline**: `/v1/turn` -- memory recall, model chat, tool exec, memory write
- **Sessions**: `/v1/sessions` -- in-memory, TTL 30min, max 100 concurrent
- **WebSocket Stream**: `WS /v1/stream/{session_id}` -- text + vision frames
- **Action Pipeline**: `/v1/actions/plan` -- 13 desktop capabilities, 4-tier safety
- **Recovery**: circuit breaker, dead letter queue, health supervisor
- **Observability**: correlation IDs, diagnostic snapshots, state backup/restore

## Release History

| Version | Tag | Highlights |
|---------|-----|------------|
| v3.3.0-dev | (in development) | Memory Ledger Ops v2, Recovery + Incident Tooling, Perception Privacy Hardening |
| v3.2.0 | `v3.2.0` | Voice Session Quality, Turn Determinism, Perception → Confirmation Ergonomics, Memory Ops Governance |
| v3.1.0 | `v3.1.0` | Stabilization Baseline: hardening test suite (39 tests), chaos fault-injection scripts, 17-gate promotion |
| v3.0.0 | `v3.0.0` | API Contract + Perception Bridge: SONIA_CONTRACT v3.0.0, identity model, typed memory ledger |
| v2.9.0 | `v2.9.0` | System Closure: model routing, EVA supervision, hybrid memory |
| v2.8.0 | `v2.8.0` | Deterministic operations: model routing cancellation, memory budget, perception gate, operator UX |

## Testing

```powershell
# Run all integration tests
S:\envs\sonia-core\python.exe -W ignore -m pytest S:\tests\integration\ -v
```

## Documentation

- `S:\docs\STAGE3_VOICE_SESSIONS.md` -- Voice session runtime
- `S:\docs\STAGE4_MULTIMODAL.md` -- Multimodal operation
- `S:\docs\STAGE5_ACTION_PIPELINE.md` -- Action pipeline + desktop adapters
- `S:\docs\STAGE6_RELIABILITY.md` -- Reliability hardening
- `S:\docs\STAGE7_OBSERVABILITY.md` -- Observability + recovery
- `S:\docs\TURN_PIPELINE.md` -- Turn pipeline design

---

**Last Updated**: 2026-02-15
**Current Version**: v3.3.0-dev
**Contract Version**: v3.0.0
**Services**: 6 active + 2 foundation
