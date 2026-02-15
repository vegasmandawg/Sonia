# SONIA: Comprehensive Architecture Analysis

**Version**: 2.10.0-dev
**Analysis Date**: 2026-02-14
**Branch**: `v2.10-dev`
**Previous Release**: v2.9.0 GA (tag `v2.9.0`)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Identity](#2-project-identity)
3. [Repository Structure (Post-Cleanup)](#3-repository-structure-post-cleanup)
4. [Core Services Architecture](#4-core-services-architecture)
5. [API Gateway (Port 7000)](#5-api-gateway-port-7000)
6. [Model Router (Port 7010)](#6-model-router-port-7010)
7. [Memory Engine (Port 7020)](#7-memory-engine-port-7020)
8. [Pipecat Voice Runtime (Port 7030)](#8-pipecat-voice-runtime-port-7030)
9. [OpenClaw Action Executor (Port 7040)](#9-openclaw-action-executor-port-7040)
10. [EVA-OS Supervisor (Port 7050)](#10-eva-os-supervisor-port-7050)
11. [Vision & Perception Services (Ports 7060-7070)](#11-vision--perception-services-ports-7060-7070)
12. [Auxiliary Services](#12-auxiliary-services)
13. [Shared Infrastructure](#13-shared-infrastructure)
14. [Data Architecture](#14-data-architecture)
15. [Configuration System](#15-configuration-system)
16. [Testing Infrastructure](#16-testing-infrastructure)
17. [Scripts & Operations Tooling](#17-scripts--operations-tooling)
18. [Release Engineering](#18-release-engineering)
19. [Training & Fine-Tuning Pipeline](#19-training--fine-tuning-pipeline)
20. [Avatar & Embodiment Assets](#20-avatar--embodiment-assets)
21. [UI Layer](#21-ui-layer)
22. [Security Architecture](#22-security-architecture)
23. [Observability Stack](#23-observability-stack)
24. [Dependency Analysis](#24-dependency-analysis)
25. [Version History & Evolution](#25-version-history--evolution)
26. [Structural Debt & Cleanup Report](#26-structural-debt--cleanup-report)
27. [Current State Assessment](#27-current-state-assessment)
28. [Known Issues & Technical Debt](#28-known-issues--technical-debt)
29. [Future Roadmap Analysis](#29-future-roadmap-analysis)
30. [Recommendations](#30-recommendations)

---

## 1. Executive Summary

SONIA (Supervised Operational Networked Intelligence Architecture) is a deterministic, voice-first, local-first AI agent platform built on Python/FastAPI microservices. The system comprises 8 core services communicating over HTTP on fixed ports (7000-7070), with a supervisory control plane (EVA-OS), persistent semantic memory (Memory Engine), real-time voice I/O (Pipecat), desktop automation (OpenClaw), and vision perception services.

The project has evolved through 10 major development stages (v2.0 through v2.10-dev) over approximately one week of intensive development (Feb 8-14, 2026), accumulating:

- **8 core services** with 160+ Python source files
- **565+ integration tests** (all green as of v2.9.0)
- **80 requirements-frozen packages** including PyTorch, Transformers, and Unsloth
- **35+ operational scripts** (promotion gates, soak tests, smoke tests)
- **18 documentation files** in `S:\docs\`
- **14 state backups** with SHA-256 manifests
- **5 release bundles** (v2.5.0, v2.8.0-rc1, v2.8.0, v2.9.0, v2.9.2)
- **~35GB of ML model weights** (Whisper, Qwen3 VLM, embeddings, reranker, TTS)

The architecture follows a strict safety model: all tool execution is risk-tiered (4 tiers), all operations are scoped to the canonical root `S:\`, and EVA-OS provides deterministic policy enforcement with full audit trails. The system is designed for single-machine deployment with optional cloud provider integration (Anthropic, OpenRouter).

**Cleanup performed during this audit**: Merged `configs/` into `config/`, removed 252 empty directories, deleted 39 debug output files, removed 9 rogue/backup files, eliminated 3 duplicate directory trees (`pipelines/`, `sonia/`, `shared/`).

---

## 2. Project Identity

| Property | Value |
|----------|-------|
| **Name** | SONIA |
| **Version** | 2.10.0-dev |
| **License** | Private/Proprietary |
| **Language** | Python 3.11 |
| **Framework** | FastAPI + Uvicorn |
| **Canonical Root** | `S:\` |
| **Git Remote** | GitHub (private) |
| **Branch** | `v2.10-dev` |
| **Python Env** | `S:\envs\sonia-core\python.exe` (Conda) |
| **Architecture Style** | Microservices (HTTP, localhost) |
| **Deployment Model** | Single-machine, local-first |
| **Primary User** | Desktop operator (Windows 11) |

---

## 3. Repository Structure (Post-Cleanup)

After this audit's cleanup, the canonical directory layout is:

```
S:\ (canonical root)
├── .claude/                    # Claude Code project settings
├── .git/                       # Git repository
├── .github/                    # GitHub Actions workflows
│   └── workflows/
│       └── sonia-build-gate.yml
├── .playwright-mcp/            # Playwright MCP config
├── .pnpm-store/                # PNPM package cache
├── .pytest_cache/              # Pytest cache
├── .ruff_cache/                # Ruff linter cache
├── .vscode/                    # VS Code settings
│
├── artifacts/                  # Build/gate artifacts
│   └── phase3/                 # Phase 3 gate results, soak logs
│
├── assets/                     # Static assets
│   └── avatar/                 # 3D model, textures, Unity project
│       ├── formats/            # FBX, HDR, IES, ACES color configs
│       ├── Live-Avatar/        # HuggingFace LiveAvatar model
│       ├── My project/         # Unity project files
│       ├── Preview/            # 43 preview renders
│       ├── textures/           # 70+ high-res texture maps
│       ├── web-ready/          # Web-optimized avatar files
│       └── *.cs, *.md          # Unity scripts, docs
│
├── backups/                    # State backups
│   └── state/                  # 14 timestamped backup snapshots
│
├── baselines/                  # Frozen baseline snapshots
│   ├── Sonia-RC1-20260208/
│   ├── Sonia-RC1.1-20260208/
│   ├── Sonia-RC1.2-20260208/
│   └── sonia_20260208-202218/
│
├── cache/                      # Runtime caches
│
├── config/                     # CONSOLIDATED configuration
│   ├── app.yaml                # Application config (from configs/)
│   ├── baseline-contract.json  # Baseline contract spec
│   ├── dependency-lock.json    # Dependency lock (SHA-256)
│   ├── env/                    # Environment templates
│   ├── logging.yaml            # Logging configuration
│   ├── models/                 # Model routing config
│   ├── policies/               # Default policy config
│   ├── policies.yaml           # EVA-OS policy tiers
│   ├── ports.yaml              # Port assignments
│   ├── runtime.yaml            # Runtime config
│   ├── schemas/                # JSON schemas (from shared/)
│   ├── services/               # Service definitions
│   ├── sonia-config.json       # CANONICAL config (primary)
│   ├── ui/                     # UI theme config
│   └── voice/                  # Voice profile config
│
├── data/                       # Persistent data
│   ├── memory/                 # Memory database
│   │   └── memory.db           # SQLite ledger (3.1MB)
│   └── sessions/               # 458 session JSON files
│
├── datasets/                   # Training datasets
│
├── docs/                       # Documentation (18 files)
│   ├── BRANCH_POLICY.md
│   ├── BUILD_SUMMARY.txt
│   ├── contracts/
│   ├── MEMORY_ENGINE_*.md
│   ├── OPENCLAW_*.md
│   ├── PIPECAT_VOICE_API.md
│   ├── RELEASE_v2.9.1.md
│   ├── reports/
│   ├── ROADMAP_V26.md
│   ├── runbooks/
│   ├── SCOPE_v2.9.2.md
│   ├── SONIA_BUILD_GUIDE.md
│   ├── SONIA_FINAL_SETUP_DOCUMENT.md
│   ├── STAGE3_VOICE_SESSIONS.md
│   ├── STAGE4_MULTIMODAL.md
│   ├── STAGE5_DESKTOP_RUNTIME.md
│   ├── STAGE6_RELIABILITY.md
│   ├── STAGE7_OBSERVABILITY.md
│   ├── STAGE8_COMPANION_EXPERIENCE.md
│   ├── STAGE9_SYSTEM_CLOSURE.md
│   ├── TURN_PIPELINE.md
│   └── UPGRADE_v2.8.0.md
│
├── integrations/               # External service integrations
│   └── openclaw/upstream/src/  # OpenClaw upstream source
│
├── issues/                     # Known issue tracking
│   ├── INFRA-FLAKY-CHAOS-TIMING.md
│   ├── INFRA-FLAKY-OLLAMA-TIMEOUT.md
│   └── INFRA-FLAKY-WS-RACE.md
│
├── logs/                       # Service logs (runtime)
│
├── models/                     # ML model weights (~35GB)
│   ├── asr/                    # faster-whisper-large-v3 (2.9GB)
│   ├── embeddings/             # Qwen3-Embedding-8B-f16.gguf (15.1GB)
│   ├── llm/base/               # Qwen3-14B-Claude-4.5-Opus_Mid-brain
│   ├── reranker/               # Qwen3-Reranker-8B.f16.gguf (16.4GB)
│   ├── tokenizers/             # Qwen3-TTS-Tokenizer-12Hz (682MB)
│   └── vlm/                    # Qwen3-VL-32B + Sonia-Qwen3-VL-32B
│
├── pipeline/                   # Persona/eval pipeline
│   ├── cli.py                  # CLI (5 subcommands)
│   ├── eval/                   # Eval harness
│   └── text/                   # Identity invariants, text processing
│
├── policies/                   # Policy definitions
│   ├── permissions/            # Permission YAML
│   └── side-effects/           # Approval matrix YAML
│
├── releases/                   # Release bundles
│   ├── v2.5.0/
│   ├── v2.8.0-rc1/
│   ├── v2.8.0/
│   ├── v2.9.0/
│   └── v2.9.2/
│
├── renders/                    # Blender render output
│
├── scripts/                    # Operations scripts (100+ files)
│   ├── bootstrap/              # Bootstrap scripts
│   ├── diagnostics/            # Health/smoke diagnostics
│   ├── feature-tests/          # Feature-specific tests
│   ├── install/                # Installation scripts
│   ├── lib/                    # Shared library (sonia-stack.ps1)
│   ├── ops/                    # Service runner scripts
│   ├── smoke/                  # Smoke tests
│   ├── testing/                # Gate/soak testing (53 files)
│   ├── blender_*.py            # Blender animation scripts
│   ├── promotion-gate-v*.ps1   # Release promotion gates
│   ├── soak_*.ps1/.py          # Soak test runners
│   └── smoke_*.ps1             # Smoke test scripts
│
├── secrets/                    # Secrets store (encrypted)
│
├── services/                   # CORE SERVICES (main codebase)
│   ├── api-gateway/            # (Port 7000) 37 files
│   ├── eva-os/                 # (Port 7050) 7 files
│   ├── mcp-server/             # MCP protocol server
│   ├── memory-engine/          # (Port 7020) 18 files
│   ├── model-router/           # (Port 7010) 8 files
│   ├── openclaw/               # (Port 7040) 18 files
│   ├── orchestrator/           # Orchestrator agent
│   ├── perception/             # (Port 7070) 2 files
│   ├── pipecat/                # (Port 7030) 18 files
│   ├── shared/                 # Shared modules (events, version)
│   ├── tool-service/           # Tool registry/executor
│   └── vision-capture/         # (Port 7060) 1 file
│
├── state/                      # Runtime state (PIDs, locks)
│
├── tests/                      # Test suites
│   ├── integration/            # 41 integration test files
│   ├── model_router/           # 4 model router tests
│   ├── pipecat/                # 3 pipecat tests
│   └── safety/                 # 2 safety/policy tests
│
├── tmp/                        # Temporary/scratch
│
├── tools/                      # External tools
│   ├── llama.cpp/              # GGUF conversion tools
│   └── python/                 # Conda Python distribution
│
├── training/                   # Training infrastructure
│   ├── hf-release/             # HuggingFace release tools
│   └── runpod/                 # RunPod training scripts
│
├── ui/                         # UI projects
│   ├── Female Advanced V2 3D Model/  # 3D model source files
│   ├── components/             # [empty after cleanup]
│   └── sonia-avatar/           # Avatar web viewer
│
├── .editorconfig               # Editor configuration
├── .env                        # Environment variables (secrets)
├── .env.example                # Environment template
├── .gitignore                  # Git ignore rules
├── ARCHITECTURE.md             # Architecture overview
├── CHANGELOG.md                # Version changelog
├── dependency-lock.json        # Root dependency lock
├── pytest.ini                  # Pytest configuration
├── README.md                   # Project README
├── requirements-dev.txt        # Development dependencies
├── requirements-frozen.txt     # Frozen pip requirements (80 pkgs)
├── ROADMAP.md                  # Development roadmap
├── RUNTIME_CONTRACT.md         # Operational contract
├── start-sonia-stack.ps1       # CANONICAL stack launcher
└── stop-sonia-stack.ps1        # Stack shutdown script
```

**Total Files** (excluding .git, node_modules, envs, __pycache__): ~1,200+
**Total Size** (excluding models/): ~3.5GB
**ML Models Size**: ~35GB

---

## 4. Core Services Architecture

SONIA follows a microservices-on-localhost pattern. All 8 services are Python/FastAPI applications running on Uvicorn, communicating over HTTP on fixed ports (7000-7070). There is no service mesh, message queue, or container orchestration -- all services run as bare processes managed by PowerShell scripts.

### Service Communication Pattern

```
                        ┌──────────────────┐
                        │   Client / UI    │
                        └────────┬─────────┘
                                 │ HTTP/WS
                                 ▼
                    ┌────────────────────────┐
                    │  API Gateway  :7000    │
                    │  (front door, sessions │
                    │   turns, streaming)    │
                    └──┬─────┬─────┬────┬───┘
                       │     │     │    │
            ┌──────────┘     │     │    └──────────┐
            ▼                ▼     ▼               ▼
    ┌───────────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
    │ Model Router  │ │  Memory  │ │Pipecat │ │ OpenClaw │
    │  :7010        │ │  Engine  │ │ :7030  │ │  :7040   │
    │ (LLM routing, │ │  :7020   │ │(voice, │ │ (desktop │
    │  providers)   │ │(persist, │ │ ASR,   │ │  actions)│
    └───────────────┘ │ search)  │ │ TTS)   │ └──────────┘
                      └──────────┘ └────────┘
                                 │
                    ┌────────────┴──────────────┐
                    │   EVA-OS Supervisor :7050 │
                    │  (policy, health probes,  │
                    │   dependency graph)       │
                    └──────────────────────────┘

    ┌───────────────────────┐  ┌──────────────────┐
    │ Vision Capture :7060  │  │ Perception :7070 │
    │ (camera, ring buffer, │  │ (VLM inference,  │
    │  privacy gate)        │  │  scene analysis) │
    └───────────────────────┘  └──────────────────┘
```

### Service Contracts

All services expose:
- `GET /healthz` -- returns `{"status": "healthy", ...}` (200 OK)
- FastAPI `main:app` pattern with Uvicorn
- JSON request/response bodies
- Correlation ID propagation (`req_xxx` format)

### Startup Sequence

The canonical launcher `start-sonia-stack.ps1` boots services in dependency order:
1. Memory Engine (no dependencies)
2. Model Router (no dependencies)
3. OpenClaw (no dependencies)
4. EVA-OS (depends on all above for health probing)
5. Pipecat (depends on Model Router, API Gateway)
6. API Gateway (depends on all above)
7. Vision Capture (optional)
8. Perception (optional, depends on Vision Capture)

---

## 5. API Gateway (Port 7000)

The API Gateway is the largest and most complex service, serving as the stable front door for all client interactions.

### File Inventory (37 source files)

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 33.5KB | FastAPI app, all route registration, lifespan |
| `action_pipeline.py` | 37.2KB | Desktop action execution pipeline |
| `vision.py` | 24.8KB | Vision streaming and frame processing |
| `ui_detection.py` | 21.2KB | UI element detection for automation |
| `ocr.py` | 20.9KB | OCR text extraction from screenshots |
| `streaming.py` | 10.0KB | WebSocket streaming utilities |
| `perception_action_gate.py` | 13.0KB | Perception-to-action safety gate |
| `operator_session.py` | 11.9KB | Operator session state machine |
| `capability_registry.py` | 11.6KB | 13 desktop capabilities registry |
| `circuit_breaker.py` | 10.6KB | Circuit breaker (CLOSED/OPEN/HALF_OPEN) |
| `tool_policy.py` | 10.8KB | 4-tier safety classification |
| `policy_engine.py` | 10.5KB | Policy evaluation engine |
| `model_call_context.py` | 8.6KB | Model call cancellation support |
| `memory_recall_context.py` | 10.0KB | Memory retrieval with token budget |
| `memory_policy.py` | 6.8KB | Memory write/read policies |
| `state_backup.py` | 9.0KB | State backup/restore with SHA-256 |
| `health_supervisor.py` | 8.6KB | Service health monitoring |
| `api_gateway.py` | 8.8KB | Core gateway logic |
| `dead_letter.py` | 6.2KB | Dead letter queue for failed actions |
| `session_manager.py` | 5.7KB | Session lifecycle (TTL, limits) |
| `vision_ingest.py` | 4.5KB | Vision frame ingestion pipeline |
| `action_audit.py` | 4.3KB | Action audit trail |
| `action_telemetry.py` | 4.3KB | Action latency instrumentation |
| `retry_taxonomy.py` | 4.5KB | 8 failure classes with retry policy |
| `turn_quality.py` | 2.1KB | Response normalization |
| `jsonl_logger.py` | 1.5KB | Structured JSONL logging |
| `action_turn_bridge.py` | 9.0KB | Bridge between turns and actions |

### Route Files

| Route | Size | Endpoints |
|-------|------|-----------|
| `routes/turn.py` | 11.0KB | `POST /v1/turn` -- main turn pipeline |
| `routes/stream.py` | 25.3KB | `WS /v1/stream/{session_id}` -- voice/text stream |
| `routes/sessions.py` | 2.6KB | `POST/GET/DELETE /v1/sessions` |
| `routes/action.py` | 4.4KB | `POST /v1/actions`, approval flow |
| `routes/chat.py` | 6.9KB | `POST /v1/chat` -- simple chat |
| `routes/ui_stream.py` | 15.6KB | UI-specific streaming |
| `api/vision_endpoints.py` | 16.9KB | Vision API endpoints |

### Schema Files

| Schema | Purpose |
|--------|---------|
| `schemas/turn.py` | TurnRequest/TurnResponse models |
| `schemas/session.py` | Session creation/state models |
| `schemas/action.py` | ActionRequest, 13 capabilities |
| `schemas/vision.py` | VisionFrame, SceneAnalysis models |

### Client Files

| Client | Target Service |
|--------|---------------|
| `clients/router_client.py` | Model Router (:7010) |
| `clients/memory_client.py` | Memory Engine (:7020) |
| `clients/openclaw_client.py` | OpenClaw (:7040) |

### Key Architectural Patterns

1. **Turn Pipeline**: `memory recall -> model chat -> tool exec -> memory write`
2. **Session Management**: In-memory, TTL 30min, max 100 concurrent
3. **Circuit Breaker**: Per-adapter, 3-failure threshold, auto-recovery
4. **Dead Letter Queue**: Failed actions captured for replay
5. **Correlation IDs**: Generated at entry, propagated to all downstream
6. **Latency Instrumentation**: asr_ms, vision_ms, memory_read_ms, model_ms, tool_ms

---

## 6. Model Router (Port 7010)

The Model Router handles LLM provider selection, health monitoring, and intelligent routing.

### File Inventory

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 26.1KB | FastAPI app, /v1/chat, /v1/embeddings, health |
| `providers.py` | 24.0KB | Anthropic + OpenRouter + Ollama providers (httpx) |
| `test_contract.py` | 9.4KB | Contract tests (21 tests) |
| `app/profiles.py` | 11.8KB | Model profiles, fallback matrix |
| `app/routing_engine.py` | 6.7KB | Routing policy (local_only, cloud_allowed, provider_pinned) |
| `app/health_registry.py` | 7.2KB | Provider health tracking, quarantine |
| `app/budget_guard.py` | 4.6KB | Token budget enforcement |
| `app/route_audit.py` | 5.2KB | Routing decision audit log |

### Provider Support

| Provider | Protocol | Status |
|----------|----------|--------|
| Ollama | HTTP (localhost:11434) | Fully implemented |
| Anthropic | HTTPS (httpx, no SDK) | Fully implemented |
| OpenRouter | HTTPS (httpx, no SDK) | Fully implemented |
| LM Studio | HTTP | Planned |
| vLLM | HTTP | Planned |

### Model Configuration (from sonia-config.json)

| Model | Context | Avg Latency | Use Case |
|-------|---------|-------------|----------|
| ollama/sonia-vlm:32b | 4096 | 2000ms | Default, vision |
| ollama/qwen2.5:7b | 4096 | 800ms | Fast chat, memory ops |
| anthropic/claude-opus-4-6 | 200K | 3000ms | Deep reasoning |
| anthropic/claude-sonnet-4-6 | 200K | 1500ms | Tool execution fallback |
| anthropic/claude-haiku-4-5 | 200K | 500ms | Light tasks |

### Fallback Matrix

The router defines task-specific fallback chains:
- **chat_low_latency**: sonia-vlm -> qwen2.5
- **reasoning_deep**: claude-opus -> claude-sonnet -> sonia-vlm
- **vision_analysis**: sonia-vlm -> qwen3-vl -> claude-sonnet
- **tool_execution**: sonia-vlm -> claude-sonnet -> qwen2.5

---

## 7. Memory Engine (Port 7020)

The Memory Engine provides persistent, searchable memory with provenance tracking and hybrid retrieval.

### File Inventory

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 29.0KB | FastAPI app, CRUD endpoints, search |
| `db.py` | 12.7KB | SQLite connection management, schema |
| `memory_engine.py` | 7.5KB | Core memory operations |
| `hybrid_search.py` | 6.3KB | HybridSearchLayer (BM25 + LIKE) |
| `core/retriever.py` | 10.5KB | Retrieval with token budget |
| `core/decay.py` | 9.3KB | Memory decay strategies |
| `core/embeddings_client.py` | 10.0KB | Embedding generation (local) |
| `core/chunker.py` | 7.1KB | Sentence-level text chunking |
| `core/bm25.py` | 6.0KB | BM25 scoring implementation |
| `core/provenance.py` | 4.6KB | ProvenanceTracker (audit_log) |
| `core/snapshot_manager.py` | 4.2KB | Context snapshot generation |
| `core/workspace_store.py` | 4.2KB | Knowledge workspace CRUD |
| `core/ledger_store.py` | 3.9KB | Append-only ledger operations |
| `core/filters.py` | 1.3KB | Query filter helpers |
| `vector/hnsw_index.py` | 12.3KB | HNSW vector index |
| `schema.sql` | 3.4KB | Full database schema |
| `test_contract.py` | 12.1KB | Contract tests |

### Database Schema

6 migrations in `db/migrations/`:
1. `001_ledger.sql` -- Core ledger table
2. `002_workspace.sql` -- Knowledge workspace
3. `003_snapshots.sql` -- Context snapshots
4. `004_indexes.sql` -- Performance indexes
5. `005_fts.sql` -- Full-text search
6. `006_provenance.sql` -- Provenance audit log

### Storage

| Store | Type | Location | Size |
|-------|------|----------|------|
| Ledger | SQLite (WAL) | `S:\data\memory.db` | 3.1MB |
| Sessions | JSON files | `S:\data\sessions\` | 458 files |
| Snapshots | In-memory | Runtime only | N/A |

### Retrieval Pipeline

1. Query arrives at `/v1/search`
2. HybridSearchLayer runs BM25 scoring + SQL LIKE fallback
3. Results ranked by composite score (relevance + recency + importance)
4. Token budget enforced (default 2000 tokens)
5. Type filters applied (fact, preference, summary, etc.)
6. Provenance metadata attached to results

---

## 8. Pipecat Voice Runtime (Port 7030)

Pipecat handles real-time voice I/O, VAD, ASR, TTS, and turn-taking.

### File Inventory

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 19.0KB | FastAPI app, WebSocket upgrade |
| `sessions.py` | 8.5KB | Voice session lifecycle |
| `events.py` | 6.2KB | Event type definitions |
| `pipecat_service.py` | 7.6KB | Core service logic |
| `app/session_manager.py` | 11.4KB | Session state management |
| `app/voice_turn_router.py` | 10.5KB | Voice turn routing |
| `app/model_router_client.py` | 8.3KB | Model Router HTTP client |
| `pipeline/vad.py` | 7.5KB | Voice Activity Detection |
| `pipeline/tts.py` | 8.0KB | Text-to-Speech pipeline |
| `pipeline/asr.py` | 7.7KB | Automatic Speech Recognition |
| `pipeline/session_manager.py` | 7.1KB | Pipeline session management |
| `app/tts_client.py` | 5.6KB | TTS client abstraction |
| `app/interruptions.py` | 5.7KB | Barge-in/interruption handling |
| `app/turn_taking.py` | 5.7KB | Turn-taking algorithm |
| `app/watchdog.py` | 6.0KB | Session health watchdog |
| `app/telemetry.py` | 4.7KB | Voice latency metrics |
| `app/latency.py` | 3.3KB | Latency tracking |
| `app/asr_client.py` | 3.7KB | ASR client abstraction |
| `websocket/server.py` | 7.9KB | WebSocket server implementation |
| `clients/gateway_stream_client.py` | 13.3KB | Gateway stream client |
| `clients/api_gateway_client.py` | 6.0KB | Gateway HTTP client |
| `routes/ws.py` | 7.2KB | WebSocket route handlers |

### Voice Pipeline

```
Audio In → VAD → ASR → Turn Detection → Model Router → TTS → Audio Out
                 ↑                                          ↓
            Barge-In ←────────── Interruption ──────────────┘
```

### Configuration (from sonia-config.json)

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16000 Hz |
| VAD Enabled | true |
| VAD Hangover | 300ms |
| Turn Finalization Silence | 1000ms |
| Streaming ASR | true |
| Barge-In | true |
| Interrupt Debounce | 150ms |
| Max Concurrent Sessions | 10 |

---

## 9. OpenClaw Action Executor (Port 7040)

OpenClaw provides deterministic desktop automation with policy governance.

### File Inventory

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 9.8KB | FastAPI app, action endpoints |
| `registry.py` | 25.7KB | 13-capability tool registry |
| `policy.py` | 6.9KB | 4-tier risk classification |
| `schemas.py` | 6.2KB | Action request/response schemas |
| `tool_catalog.json` | 12.5KB | Tool definitions catalog |
| `executors/desktop_exec.py` | 16.9KB | Desktop automation (ctypes) |
| `executors/file_exec.py` | 9.7KB | File operations |
| `executors/web_exec.py` | 10.7KB | Web/browser operations |
| `executors/shell_exec.py` | 5.2KB | Shell command execution |
| `executors/browser_exec.py` | 5.7KB | Browser control |
| `executors/notification_exec.py` | 6.3KB | Notification delivery |
| `app/policy_engine.py` | 17.3KB | Policy evaluation |
| `app/confirmations.py` | 16.4KB | Confirmation queue (120s TTL) |
| `app/action_guard.py` | 11.7KB | Action safety guard |
| `test_contract.py` | 14.1KB | Contract tests |
| `test_executors.py` | 14.0KB | Executor tests |
| `validate.ps1` | 9.4KB | Validation script |

### 13 Desktop Capabilities

| Capability | Risk Tier | Description |
|------------|-----------|-------------|
| file.read | safe_read | Read file contents |
| file.write | guarded_medium | Write file contents |
| shell.run | guarded_high | Execute shell commands |
| app.launch | guarded_low | Launch applications |
| app.close | guarded_low | Close applications |
| clipboard.read | safe_read | Read clipboard |
| clipboard.write | guarded_low | Write clipboard |
| keyboard.type | guarded_medium | Type text |
| keyboard.hotkey | guarded_medium | Send keyboard shortcuts |
| mouse.click | guarded_medium | Click at coordinates |
| window.list | safe_read | List open windows |
| window.focus | guarded_low | Focus a window |
| browser.open | guarded_low | Open URL in browser |

### Desktop Adapters

| Adapter | Technology | SLO (p95) |
|---------|-----------|-----------|
| ctypes (native) | Python ctypes + Win32 API | < 200ms |
| subprocess (PowerShell) | PowerShell subprocesses | < 2000ms |
| dry-run | Validate-only (no side effects) | < 2000ms |

---

## 10. EVA-OS Supervisor (Port 7050)

EVA-OS is the supervisory control plane providing policy decisions, service health monitoring, and dependency graph management.

### File Inventory

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 14.3KB | FastAPI app, health aggregation |
| `eva_os.py` | 18.8KB | Core EVA-OS logic |
| `eva_os_service.py` | 11.3KB | Service layer |
| `service_supervisor.py` | 10.8KB | ServiceSupervisor (5-state machine) |
| `app/orchestrator.py` | 10.2KB | Orchestration logic |

### Service Supervisor State Machine

```
UNKNOWN → STARTING → HEALTHY → DEGRADED → UNHEALTHY
    ↑                    ↑         │          │
    └────────────────────┴─────────┴──────────┘
                    (recovery)
```

States: UNKNOWN, STARTING, HEALTHY, DEGRADED, UNHEALTHY

The supervisor performs `/healthz` probes against all registered services, tracks failure counts, and emits state transition events through the shared EventBus.

### Dependency Graph

EVA-OS maintains a dependency graph:
- API Gateway depends on: Model Router, Memory Engine, OpenClaw
- Pipecat depends on: Model Router, API Gateway
- Perception depends on: Vision Capture, Model Router

---

## 11. Vision & Perception Services (Ports 7060-7070)

### Vision Capture (Port 7060)

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 13.6KB | Camera capture, ring buffer, privacy gate |

Features:
- **Privacy Hard Gate**: Vision disabled by default (`default_mode: "off"`)
- **Ring Buffer**: 300-frame circular buffer
- **Resolution Modes**: Ambient (320x240 @ 1fps) / Active (640x480 @ 10fps)
- **Max Frame Size**: 1MB per frame

### Perception (Port 7070)

| Module | Size | Purpose |
|--------|------|---------|
| `main.py` | 17.4KB | Event-driven VLM inference |
| `pipeline_runner.py` | 8.4KB | Inference pipeline execution |

Features:
- **VLM Inference**: Real inference using Qwen3-VL-32B
- **Event Bus**: Receives `perception.trigger` events
- **Scene Analysis**: Structured output with confirmation required
- **Fail-Closed**: Any pipeline error returns safe default (no action)

---

## 12. Auxiliary Services

### MCP Server (`services/mcp-server/`)

| Module | Size | Purpose |
|--------|------|---------|
| `server.py` | 19.4KB | MCP protocol server for Claude Code |
| `test_server.py` | 10.8KB | Server tests |
| `claude_desktop_config.json` | 180B | Claude Desktop integration config |

Provides SONIA capabilities to Claude Code via the Model Context Protocol.

### Orchestrator (`services/orchestrator/`)

| Module | Size | Purpose |
|--------|------|---------|
| `agent.py` | 23.7KB | Multi-step agent orchestration |
| `orchestrator_service.py` | 13.5KB | Orchestrator service layer |

The orchestrator runs on port 8000 (separate from the core boot sequence) and coordinates multi-step task execution.

### Tool Service (`services/tool-service/`)

| Module | Size | Purpose |
|--------|------|---------|
| `tool_service.py` | 11.9KB | Tool execution service |
| `tool_registry.py` | 16.6KB | Tool registration/discovery |
| `executor.py` | 14.3KB | Tool execution engine |
| `standard_tools.py` | 17.7KB | Built-in tool definitions |

Legacy tool execution service (predates OpenClaw).

---

## 13. Shared Infrastructure

### Shared Modules (`services/shared/`)

| Module | Purpose |
|--------|---------|
| `events.py` | EventEnvelope, 20 event types, correlation IDs |
| `event_bus.py` | In-process event bus with pub/sub |
| `version.py` | Canonical `SONIA_VERSION = "2.10.0-dev"` |

### Event System

The shared EventEnvelope provides:
- 20 event types (session.created, turn.completed, action.executed, etc.)
- Correlation ID propagation
- Timestamp and source service tracking
- JSON-serializable payloads

### Pipeline Modules (`pipeline/`)

| Module | Purpose |
|--------|---------|
| `cli.py` | CLI with 5 subcommands (build, validate, eval, compare, export) |
| `text/process.py` | Text processing pipeline |
| `text/identity_invariants.py` | 13 identity anchors, 3 severity levels |
| `eval/harness.py` | 5-dimensional evaluation harness |
| `eval/seed_prompts.jsonl` | Evaluation seed prompts |

The pipeline manages persona manifests (schema v1.1.0) with deterministic build IDs.

---

## 14. Data Architecture

### Memory Database

| Component | Technology | Location |
|-----------|-----------|----------|
| Ledger | SQLite (WAL mode) | `S:\data\memory.db` |
| Sessions | JSON files | `S:\data\sessions\` (458 files) |
| Vector Index | HNSW (in-memory) | Runtime only |

### State Backups

14 timestamped backups in `S:\backups\state\`, each containing:
- `actions.json` -- Executed action history
- `breakers.json` -- Circuit breaker state
- `dead_letters.json` -- Dead letter queue
- `manifest.json` -- SHA-256 checksums

### ML Model Storage

| Model | Type | Size | Format |
|-------|------|------|--------|
| faster-whisper-large-v3 | ASR | 2.9GB | CTranslate2 |
| Qwen3-Embedding-8B | Embeddings | 15.1GB | GGUF (f16) |
| Qwen3-Reranker-8B | Reranker | 16.4GB | GGUF (f16) |
| Qwen3-TTS-Tokenizer-12Hz | TTS | 682MB | SafeTensors |
| Qwen3-VL-32B-Instruct | VLM (base) | ~20GB | SafeTensors |
| Sonia-Qwen3-VL-32B | VLM (fine-tuned) | ~20GB | SafeTensors |
| Qwen3-14B-Claude-4.5-Opus_Mid-brain | LLM (base) | ~14GB | SafeTensors |

---

## 15. Configuration System

### Configuration Hierarchy (Post-Cleanup)

```
config/
├── sonia-config.json        ← CANONICAL (primary, all services read this)
├── app.yaml                 ← Application-level config (merged from configs/)
├── ports.yaml               ← Port assignments (hard-coded)
├── logging.yaml             ← Logging formatters and handlers
├── policies.yaml            ← EVA-OS tier policies
├── runtime.yaml             ← Runtime parameters
├── baseline-contract.json   ← Baseline contract specification
├── dependency-lock.json     ← Dependency SHA-256 locks
├── env/
│   └── .env.template        ← Environment variable template
├── models/
│   └── model-routing.yaml   ← Model routing configuration
├── schemas/                 ← JSON schemas (merged from shared/)
│   ├── envelope.json
│   ├── envelopes.json
│   └── event.schema.json
├── services/
│   └── services.yaml        ← Service definitions
├── ui/
│   └── theme.yaml           ← UI theme configuration
└── voice/
    └── voice-profile.yaml   ← Voice profile settings
```

### Configuration Conflicts Noted

1. `config/app.yaml` references `/health` endpoints; canonical config uses `/healthz`
2. `config/app.yaml` references `configs: S:\configs` (stale path, now `S:\config`)
3. `sonia-config.json` references `S:\shared\schemas` (moved to `S:\config\schemas`)
4. Root `dependency-lock.json` duplicates `config/dependency-lock.json`

**Recommendation**: Update stale path references in `app.yaml` and `sonia-config.json`.

---

## 16. Testing Infrastructure

### Test Distribution

| Suite | Files | Approx Tests | Location |
|-------|-------|-------------|----------|
| Integration | 41 | ~400+ | `tests/integration/` |
| Model Router | 4 | ~40 | `tests/model_router/` |
| Pipecat | 3 | ~30 | `tests/pipecat/` |
| Safety | 2 | ~20 | `tests/safety/` |
| Memory Engine | 2 | ~15 | `services/memory-engine/tests/` |
| Service Contracts | 5 | ~75 | `services/*/test_contract.py` |
| **Total** | **57** | **~580+** | |

### Test Naming Convention

Tests follow version-prefixed naming:
- `test_turn_pipeline.py` -- Stage 2 (core pipeline)
- `test_v26_*.py` -- v2.6 companion experience
- `test_v27_*.py` -- v2.7 action execution
- `test_v28_*.py` -- v2.8 deterministic operations
- `test_v29_*.py` -- v2.9 system closure
- `test_v210_*.py` -- v2.10 current development

### Pytest Configuration

```ini
[pytest]
markers =
    integration: Integration tests requiring running services
    smoke: Quick smoke tests
    soak: Long-running soak tests
    v28: v2.8 milestone tests
    v210: v2.10 milestone tests
```

### Soak Tests

| Script | Purpose | Workload |
|--------|---------|----------|
| `soak_stage3_sessions.ps1` | Session lifecycle stress | 3x2 default |
| `soak_stage4_multimodal.ps1` | Multimodal pipeline stress | Configurable |
| `soak_stage5_actions.ps1` | Action throughput | 200+ actions |
| `soak_stage6_latency.ps1` | SLO compliance | 240 actions |
| `soak_v28_rc1.ps1` | v2.8 RC1 validation | 700 operations |

---

## 17. Scripts & Operations Tooling

### Script Categories

| Category | Count | Purpose |
|----------|-------|---------|
| `ops/` | 28 | Service runners, stack management |
| `testing/` | 50 | Gate validators, soak runners, diagnostics |
| `diagnostics/` | 6 | Health checks, smoke tests |
| `bootstrap/` | 2 | Initial setup scripts |
| `feature-tests/` | 3 | Feature-specific validation |
| `blender_*.py` | 13 | 3D model animation/rendering |
| `promotion-gate-*.ps1` | 6 | Release promotion gates |
| `soak_*.ps1` | 5 | Soak test launchers |
| `smoke_*.ps1` | 3 | Smoke test suites |
| `cadence-*.ps1` | 3 | Daily/weekly/monthly cadence |

### Canonical Scripts

| Script | Purpose |
|--------|---------|
| `start-sonia-stack.ps1` | Stack launcher (18.9KB, comprehensive) |
| `stop-sonia-stack.ps1` | Stack shutdown |
| `scripts/lib/sonia-stack.ps1` | Shared PowerShell library |
| `scripts/ops/run-*.ps1` | Individual service runners |
| `scripts/qualify-change.ps1` | Change qualification pipeline |
| `scripts/promote-rc.ps1` | Release candidate promotion |

### Release Promotion Gates

| Version | Script | Gates |
|---------|--------|-------|
| v2.5.0 | `promotion-gate.ps1` | 6 gates |
| v2.5.0-rc1 | `promotion-gate-v2.ps1` | 12 gates |
| v2.6 | `promotion-gate-v26.ps1` | 16 gates |
| v2.8 | `promotion-gate-v28.ps1` | 14 gates |
| v2.9 | `promotion-gate-v29.ps1` | 12 gates |

---

## 18. Release Engineering

### Release History

| Version | Tag | Date | Key Features |
|---------|-----|------|-------------|
| v2.5.0-stage5 | `v2.5.0-stage5` | Feb 8 | Action pipeline + desktop adapters |
| v2.5.0-rc1 | `v2.5.0-rc1` | Feb 8 | Reliability hardening |
| v2.5.0 GA | `v2.5.0` | Feb 9 | Observability + recovery drills |
| v2.6 | N/A | Feb 9 | Companion experience layer |
| v2.8.0-rc1 | `v2.8.0-rc1` | Feb 10 | Deterministic operations |
| v2.8.0 GA | `v2.8.0` | Feb 10 | GA artifacts |
| v2.9.0 | `v2.9.0` | Feb 11 | System closure |
| v2.9.2 | N/A | Feb 12 | Legacy closure |
| v2.10.0-dev | N/A | Feb 13-14 | VLM inference, chunker, MCP |

### Release Bundle Contents

Each release in `S:\releases\v*.*.*\` contains:
- `release-manifest.json` -- SHA-256 checksums for all artifacts
- `gate-report.json` -- Promotion gate results
- `dependency-lock.json` -- Frozen dependency hashes
- `CHANGELOG.md` -- Version-specific changelog
- `soak-report.json` -- Soak test results (when applicable)

### Rollback Scripts

| Script | Target |
|--------|--------|
| `rollback-to-stage5.ps1` | Roll back to v2.5.0-stage5 |
| `rollback-to-v25.ps1` | Roll back to v2.5.0 GA |

---

## 19. Training & Fine-Tuning Pipeline

### Training Infrastructure (`training/`)

#### RunPod Training (`training/runpod/`)

| Module | Purpose |
|--------|---------|
| `train_sonia_qwen3vl.py` | Fine-tune Qwen3-VL-32B on Sonia data |
| `combine_datasets.py` | Dataset combination (v1) |
| `combine_datasets_v2.py` | Dataset combination (v2, improved) |
| `merge_push_sharded.py` | Sharded model merge + HF push |
| `merge_streaming.py` | Streaming merge (memory efficient) |
| `quantize_gguf.py` | GGUF quantization |
| `quantize_gguf_v2.py` | Improved quantization |
| `setup_and_train.sh` | RunPod setup script |

#### Training Data (`training/runpod/data/`)

| File | Size | Purpose |
|------|------|---------|
| `sonia_combined_train.jsonl` | 7.8MB | Training split |
| `sonia_combined_val.jsonl` | 526KB | Validation split |
| `sonia_combined_test.jsonl` | 579KB | Test split |

#### HuggingFace Release (`training/hf-release/`)

Tools for publishing models to HuggingFace:
- `upload_release.py` -- Upload model to HF Hub
- `verify_hub.py` -- Verify uploaded model
- `tag_release.py` -- Tag release on HF

### GGUF Conversion Tools (`tools/llama.cpp/`)

| Tool | Size | Purpose |
|------|------|---------|
| `convert_hf_to_gguf.py` | 564KB | HuggingFace to GGUF conversion |
| `convert_lora_to_gguf.py` | 20.6KB | LoRA to GGUF conversion |

---

## 20. Avatar & Embodiment Assets

### 3D Model Assets (`assets/avatar/`)

The avatar system provides visual embodiment for Sonia:

| Asset Type | Count/Size | Format |
|------------|-----------|--------|
| 3D Models | 3 files | FBX, Blend, MAX |
| Textures | 70+ maps | TIF (16-bit, 4K-16K) |
| Displacement Maps | 12 masks | TIF |
| Hair Maps | 5 maps | JPG |
| HDR Environments | 26 | HDR (EXR) |
| IES Light Profiles | 5 | IES |
| Preview Renders | 43 | JPG |
| Web-Ready Assets | 4 files | FBX, GLTF, PNG |

### Texture Map Types

| Type | Purpose | Typical Resolution |
|------|---------|-------------------|
| DM (Diffuse/Color) | Base color | 8K-16K |
| NRM (Normal) | Surface detail | 8K |
| SPEC (Specular) | Reflectivity | 4K-8K |
| SSS (Subsurface) | Skin translucency | 4K |
| AO (Ambient Occlusion) | Shadow detail | 8K |
| MASK files | Material separation | 4K-8K |

### Unity Integration (`assets/avatar/My project/`)

Contains a Unity project with:
- `AIAnimationController.cs` -- AI-driven animation
- `AIProceduralAnimator.cs` -- Procedural motion
- `RealtimeMotionGenerator.cs` -- Real-time motion
- `VideoRecorder.cs` -- Video capture
- ML Agents training config

### Live Avatar Model (`assets/avatar/Live-Avatar/`)

HuggingFace LiveAvatar model (1.35GB safetensors) for real-time avatar animation.

### Blender Scripts (`scripts/blender_*.py`)

13 Blender Python scripts for:
- Model rendering (`blender_render_femadv.py` -- 38KB)
- Animation (`blender_animate_femadv.py` -- 26KB)
- Customization (`blender_customize_sonia.py` -- 26KB)
- Diagnostics (material dumps, bone dumps, scene analysis)

---

## 21. UI Layer

### UI Projects (`ui/`)

| Project | Purpose | Status |
|---------|---------|--------|
| `Female Advanced V2 3D Model/` | Source 3D model files | Active asset |
| `sonia-avatar/` | Web-based avatar viewer | Prototype |

### Companion UI Configuration (from sonia-config.json)

```json
{
  "window_width": 480,
  "window_height": 720,
  "theme": "dark_red",
  "avatar_placeholder": true,
  "websocket_reconnect_ms": 3000,
  "max_reconnect_attempts": 10
}
```

### UI Architecture (from Stage 8 design)

The planned companion UI uses:
- **State Management**: Zustand with 5-state FSM
- **ACK Model**: Optimistic updates with rollback
- **Connection Manager**: WebSocket with exponential backoff
- **Diagnostics Panel**: Real-time service monitoring

---

## 22. Security Architecture

### Trust Boundaries

```
UNTRUSTED: Client input, LLM outputs, external APIs
    ↓ (validated, sanitized)
TRUSTED: API Gateway, EVA-OS (policy layer)
    ↓ (policy-checked, approval tokens)
TRUSTED: Model Router, Memory Engine, Pipecat
    ↓ (approval token verified)
EXECUTION: OpenClaw (action execution with audit)
```

### 4-Tier Risk Classification

| Tier | Label | Approval | Examples |
|------|-------|----------|----------|
| 0 | safe_read | Auto-execute | file.read, window.list, clipboard.read |
| 1 | guarded_low | 30s auto-gate | app.launch, clipboard.write, browser.open |
| 2 | guarded_medium | Explicit approval | file.write, keyboard.type, mouse.click |
| 3 | guarded_high | Approval + code | shell.run, filesystem.delete |

### Root Contract

All filesystem operations scoped to `S:\`. The root contract is enforced at:
1. EVA-OS policy layer (reject paths outside root)
2. OpenClaw file executor (validate paths)
3. API Gateway action pipeline (pre-check)

### Secrets Management

- `.env` file at root (gitignored)
- `.env.example` template (10KB, comprehensive)
- `secrets/` directory for encrypted secrets
- No secrets in configuration files (except `.env`)

---

## 23. Observability Stack

### Logging

| Component | Location | Format |
|-----------|----------|--------|
| Service stdout | `S:\logs\services\<name>.out.log` | JSON |
| Service stderr | `S:\logs\services\<name>.err.log` | Text |
| Gateway turns | `S:\logs\gateway\turns.jsonl` | JSONL |
| Gateway sessions | `S:\logs\gateway\sessions.jsonl` | JSONL |
| Gateway tools | `S:\logs\gateway\tools.jsonl` | JSONL |
| Model routes | `S:\logs\services\model-router\routes.jsonl` | JSONL |

### Correlation ID Traceability

All entry points generate `req_xxx` correlation IDs that propagate:
- API Gateway -> Model Router (via X-Correlation-ID header)
- API Gateway -> Memory Engine (via X-Correlation-ID header)
- API Gateway -> OpenClaw (via X-Correlation-ID header)
- WebSocket streams carry correlation IDs in each message

### Health Monitoring

- Each service exposes `GET /healthz`
- EVA-OS ServiceSupervisor probes all services
- Circuit breaker tracks failure counts per adapter
- Breaker metrics endpoint: `GET /v1/breakers/metrics`

### Diagnostics

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/diagnostics/snapshot` | Full system diagnostic snapshot |
| `GET /v1/backups` | List state backups |
| `GET /v1/backups/verify` | Verify backup integrity |
| `POST /v1/backups` | Create state backup |
| `POST /v1/restore/dlq` | Restore dead letter queue |

### Incident Response

`scripts/export-incident-bundle.ps1` exports:
- Service logs (configurable time window)
- Health check results
- Circuit breaker state
- Dead letter queue contents
- System diagnostics snapshot

---

## 24. Dependency Analysis

### Core Dependencies (requirements-frozen.txt)

| Category | Packages | Key Versions |
|----------|----------|-------------|
| **Web Framework** | FastAPI, Starlette, Uvicorn | 0.116.1, 0.47.3, 0.35.0 |
| **ML/AI** | PyTorch, Transformers, Unsloth | 2.10.0+cu128, 4.57.6, 2026.1.4 |
| **Data** | NumPy, Pandas, PyArrow | 2.3.5, 3.0.0, 23.0.0 |
| **HTTP** | httpx, aiohttp, requests | 0.28.1, 3.13.3, 2.32.5 |
| **Validation** | Pydantic, msgspec | 2.11.7, 0.20.0 |
| **Tokenizers** | tokenizers, sentencepiece | 0.22.2, 0.2.1 |
| **Training** | accelerate, peft, trl, bitsandbytes | 1.12.0, 0.18.1, 0.24.0, 0.49.1 |
| **WebSocket** | websockets | 16.0 |
| **System** | psutil | 7.2.2 |

### Notable Dependencies

- **PyTorch 2.10.0+cu128**: CUDA 12.8 build with xformers and triton-windows
- **websockets 16.0**: Breaking change from v15 (`timeout` -> `open_timeout`/`close_timeout`)
- **Unsloth 2026.1.4**: Fine-tuning optimization library
- **cut-cross-entropy**: Training loss optimization

### Dependency Risks

1. **PyTorch CUDA coupling**: Tied to CUDA 12.8; GPU driver updates could break
2. **websockets v16**: Already hit breaking API change (lesson documented)
3. **Unsloth**: Rapidly evolving; may require frequent updates
4. **FastAPI 0.116**: Major version coming; may require migration

---

## 25. Version History & Evolution

### Development Timeline

| Date | Version | Milestone |
|------|---------|-----------|
| Feb 8, 2026 | v1.0-2.5.0 | Foundation through Stage 5 (action pipeline) |
| Feb 8, 2026 | v2.5.0-rc1 | Stage 6: Reliability hardening |
| Feb 9, 2026 | v2.5.0 GA | Stage 7: Observability + recovery drills |
| Feb 9, 2026 | v2.6 | Stage 8: Companion experience layer |
| Feb 10, 2026 | v2.8.0 | Deterministic operations (skipped v2.7) |
| Feb 11, 2026 | v2.9.0 | System closure (model routing, EVA supervision, memory hybrid) |
| Feb 12, 2026 | v2.9.2 | Legacy closure (schema freeze, flaky fix, markers removed) |
| Feb 13-14, 2026 | v2.10.0-dev | VLM inference, sentence chunker, MCP boot, policy tests |

### Stage Progression

**Stage 2 (Turn Pipeline)**: Established the core `memory recall -> model chat -> tool exec -> memory write` loop. 8 integration tests.

**Stage 3 (Voice Sessions)**: Added session control plane, WebSocket streaming, tool safety gate, confirmation queue. 25 tests.

**Stage 4 (Multimodal)**: Vision ingestion, turn quality controls, memory write/read policies, latency instrumentation. 26 tests.

**Stage 5 (Action Pipeline)**: 13 desktop capabilities, 4-tier safety, circuit breaker, dead letter queue, health supervisor. 78 tests.

**Stage 6 (Reliability)**: Retry taxonomy (8 failure classes), DLQ replay, breaker metrics, SLO budgets, release artifacts. 27 tests.

**Stage 7 (Observability)**: Correlation ID traceability, incident bundle export, chaos suite, state backup/restore. 25 tests.

**Stage 8 (Companion)**: Persona manifests, vision capture/perception services, embodiment UI design (Zustand FSM). 17 tests.

**v2.8 (Deterministic Ops)**: Model call cancellation, memory budget, perception bypass-proof gate, operator state machine. 156 tests.

**v2.9 (System Closure)**: Real Anthropic/OpenRouter providers, EVA-OS supervision with health probes, BM25 hybrid search. 92 tests.

**v2.10 (Current Dev)**: Real VLM inference, sentence-level chunking, MCP server integration, expanded policy tests.

### Test Count Evolution

| Version | New Tests | Total |
|---------|-----------|-------|
| Stage 2 | 8 | 8 |
| Stage 3 | 25 | 33 |
| Stage 4 | 26 | 59 |
| Stage 5 | 78 | 137 |
| Stage 6 | 27 | 164 |
| Stage 7 | 25 | 189 |
| Stage 8 | 17 | 206 |
| v2.8 | 156 | 362 (+ model router/pipecat) |
| v2.9 | 92 | ~565 |
| v2.10 | ~15+ | ~580+ |

---

## 26. Structural Debt & Cleanup Report

### Cleanup Performed (This Audit)

| Action | Count | Details |
|--------|-------|---------|
| Empty directories removed | 252 | Across all top-level directories |
| Debug output files removed | 39 | Test results, git dumps, bone dumps |
| Rogue files removed | 5 | DumpStack.log.tmp, New Text Document.txt x3 |
| Backup scripts removed | 4 | .bak.ps1 files in lib/ and ops/ |
| Duplicate dir merged | 1 | `configs/` -> `config/` (4 YAML files) |
| Duplicate dir removed | 1 | `pipelines/` (entirely empty placeholder) |
| Duplicate dir removed | 1 | `sonia/` (empty, content in `assets/`) |
| Duplicate dir merged | 1 | `shared/` schemas -> `config/schemas/` |

### Remaining Structural Debt

1. **`services/tool-service/`**: Legacy tool execution service that predates OpenClaw. Functionality overlaps significantly with OpenClaw. Should be assessed for removal or explicit deprecation.

2. **`services/orchestrator/`**: Runs on port 8000, not integrated into the main boot sequence. Role unclear relative to EVA-OS.

3. **Multiple config sources**: `sonia-config.json` (JSON) vs `app.yaml` / `ports.yaml` / `policies.yaml` (YAML). Some values conflict (health endpoint `/health` vs `/healthz`).

4. **Stale path references**: `sonia-config.json` still references `S:\shared\schemas` (now `S:\config\schemas`). `app.yaml` references `configs: S:\configs` (now `S:\config`).

5. **Large __pycache__ directories**: 27+ files in api-gateway `__pycache__` alone. Consider adding `__pycache__/` to `.gitignore` more aggressively.

6. **458 session JSON files** in `S:\data\sessions\`: Most are 233 bytes (empty sessions from test runs). Should be periodically pruned.

7. **`baselines/` directory**: 4 frozen baseline snapshots from Feb 8. Unclear if still needed. ~50MB of duplicate code.

8. **`artifacts/phase3/`**: 68 files of phase 3 gate results, logs, and evidence. Historical only. Could be archived.

9. **`tests/integration/__pycache__/`**: 94 compiled test cache files (~4MB). Should be cleaned periodically.

10. **COMPLETION_REPORT.md files in services**: `PHASE_F_COMPLETION_REPORT.md`, `PHASE_G_COMPLETION_REPORT.md`, `PHASE_H_COMPLETION_REPORT.md` are one-time artifacts that don't belong in service directories.

---

## 27. Current State Assessment

### System Health: HEALTHY

| Aspect | Status | Notes |
|--------|--------|-------|
| Core Services | 6/6 implemented | api-gw, model-router, memory, pipecat, openclaw, eva-os |
| Vision Services | 2/2 implemented | vision-capture, perception |
| Integration Tests | ~580+ passing | All green as of v2.9.0 |
| Release Discipline | Strong | Promotion gates, soak tests, SHA-256 manifests |
| Documentation | Good | 18 doc files, stage-by-stage coverage |
| Security Model | Complete | 4-tier safety, root contract, audit trails |
| Observability | Good | Correlation IDs, JSONL logging, diagnostics |

### Maturity Assessment

| Component | Maturity | Evidence |
|-----------|----------|---------|
| API Gateway | Production-ready | Comprehensive routes, error handling, circuit breaker |
| Model Router | Production-ready | Multi-provider, health tracking, fallback matrix |
| Memory Engine | Production-ready | Hybrid search, provenance, migrations |
| Pipecat | Beta | Full pipeline but limited real-world testing |
| OpenClaw | Production-ready | 13 capabilities, safety gate, audit |
| EVA-OS | Beta | Real supervision, but limited orchestration |
| Vision Capture | Alpha | Privacy gate works, but minimal testing |
| Perception | Alpha | VLM inference works, limited integration |
| MCP Server | Alpha | Basic implementation, new in v2.10 |
| UI | Prototype | Design complete, implementation minimal |

### Code Quality Metrics

| Metric | Value |
|--------|-------|
| Python source files | ~160+ |
| Total source code | ~600KB+ |
| Test files | 57 |
| Test-to-source ratio | ~0.36 |
| Largest file | `action_pipeline.py` (37.2KB) |
| Average service size | ~15 files |
| Configuration files | 12+ |
| Documentation files | 18 |

---

## 28. Known Issues & Technical Debt

### Documented Issues (`issues/`)

1. **INFRA-FLAKY-CHAOS-TIMING.md**: Timing-sensitive chaos tests occasionally fail under load
2. **INFRA-FLAKY-OLLAMA-TIMEOUT.md**: Ollama model loading timeouts on cold start
3. **INFRA-FLAKY-WS-RACE.md**: WebSocket race condition in rapid connect/disconnect

### Architectural Debt

1. **No container orchestration**: All services as bare processes. No auto-restart, no resource limits, no scaling.

2. **In-memory session state**: Sessions are in-memory only (API Gateway). Service restart loses all active sessions.

3. **SQLite at scale**: Memory Engine uses SQLite. Adequate for single-user but won't scale to multi-user without migration to PostgreSQL.

4. **No authentication/authorization**: No user authentication. The system assumes a single trusted operator.

5. **No TLS**: All inter-service communication is plain HTTP on localhost. Acceptable for single-machine but not for networked deployment.

6. **Monolithic main.py files**: API Gateway's `main.py` is 33.5KB, Memory Engine's is 29KB. These should be decomposed into smaller modules.

7. **Dual configuration format**: Mix of JSON (`sonia-config.json`) and YAML (`*.yaml`) configs with overlapping/conflicting values.

8. **PowerShell-specific operations**: All operational scripts are PowerShell (.ps1), limiting portability to Windows only.

9. **No CI/CD pipeline**: `sonia-build-gate.yml` exists in `.github/workflows/` but the system primarily relies on manual promotion gates.

10. **Vector index not persistent**: HNSW vector index exists only in memory. Restarts require re-indexing.

### Code-Level Debt

1. `__pycache__` directories tracked in git (should be gitignored more strictly)
2. Test files duplicate `sys.path.insert(0, ...)` boilerplate
3. Several `COMPLETION_REPORT.md` files mixed with source code
4. Legacy `VISION_STREAMING_API.md` in api-gateway directory
5. Duplicate `.fbx` files across `assets/avatar/` and `ui/Female Advanced V2 3D Model/`

---

## 29. Future Roadmap Analysis

### Current Roadmap (from ROADMAP.md)

The published roadmap spans v1.0 through v2.0:

| Phase | Version | Target | Status |
|-------|---------|--------|--------|
| Phase 0-H | v1.0.0 | Foundation | COMPLETE (exceeded) |
| Phase D | v1.1.0 | Memory Intelligence | COMPLETE (in v2.9) |
| Phase E | v1.2.0 | Voice Excellence | PARTIALLY COMPLETE (Pipecat) |
| Phase F | v1.3.0 | Vision & Automation | PARTIALLY COMPLETE (v2.8-2.10) |
| Phase G | v1.4.0 | Governance at Scale | PARTIALLY COMPLETE (EVA-OS) |
| Phase H | v1.5.0 | Analytics & Observability | PARTIALLY COMPLETE (Stage 7) |
| Phase I | v2.0.0 | Enterprise Ready | NOT STARTED |

### Roadmap vs Reality

The actual development has **significantly outpaced** the published roadmap. Features planned for Q4 2026 - Q2 2027 have already been partially or fully implemented. The version numbering jumped from the planned v1.x to v2.x, and the system is currently at v2.10-dev.

### Recommended Next Steps (v2.10+ and Beyond)

#### Near-Term (v2.10 GA)

1. **Stabilize MCP server integration** -- Complete the Claude Code MCP bridge
2. **VLM inference hardening** -- Error handling, timeout management, GPU memory guards
3. **Sentence chunker validation** -- Test with real document corpus
4. **Policy engine test coverage** -- Expand v2.10 policy tests
5. **Config cleanup** -- Resolve stale paths, unify JSON/YAML conflicts

#### Medium-Term (v2.11-2.12)

1. **Persistent vector index** -- Save/load HNSW to disk
2. **Session persistence** -- Redis or SQLite-backed sessions
3. **User authentication** -- JWT or OAuth2 for multi-user support
4. **TLS for inter-service comms** -- Self-signed certs for localhost
5. **Container packaging** -- Docker/Podman images for each service
6. **CI/CD activation** -- Flesh out GitHub Actions workflow

#### Long-Term (v3.0)

1. **PostgreSQL migration** -- Replace SQLite for multi-user scale
2. **Message queue** -- RabbitMQ/Redis Streams for async events
3. **Kubernetes deployment** -- Helm charts, service mesh
4. **Multi-tenant isolation** -- Per-user data partitioning
5. **Plugin system** -- Third-party tool/executor extensions
6. **Mobile/web client** -- React/Next.js companion app

---

## 30. Recommendations

### Critical (Do Now)

1. **Fix stale config references**: Update `sonia-config.json` path for schemas (`S:\shared\schemas` -> `S:\config\schemas`). Update `app.yaml` health endpoints (`/health` -> `/healthz`) and directory reference (`S:\configs` -> `S:\config`).

2. **Prune session files**: 458 session files in `S:\data\sessions\` (most are empty test artifacts). Add periodic cleanup to cadence scripts.

3. **Add `__pycache__/` to .gitignore**: Prevent compiled Python files from being tracked.

### High Priority (This Sprint)

4. **Deprecate `services/tool-service/`**: Mark as deprecated, document migration path to OpenClaw. Remove in next major version.

5. **Move COMPLETION_REPORT files**: Move `PHASE_*_COMPLETION_REPORT.md` files from service directories to `docs/reports/`.

6. **Archive `baselines/` directory**: Move to cold storage or compress. These snapshots are 2+ weeks old.

7. **Archive `artifacts/phase3/`**: Historical gate results. Compress and move to `releases/` or cold storage.

8. **Unify configuration format**: Migrate all YAML configs to a single `sonia-config.json` or convert to all-YAML with a single entry point.

### Medium Priority (Next Release)

9. **Decompose large files**: Break up `api-gateway/main.py` (33.5KB) and `memory-engine/main.py` (29KB) into smaller, focused modules.

10. **Add health check to CI**: Activate `sonia-build-gate.yml` with at least import checks and unit tests.

11. **Persistent vector index**: Critical for production use. HNSW rebuild on every restart is expensive with large corpora.

12. **Session persistence**: Essential before any multi-session or production deployment.

### Low Priority (Backlog)

13. **Cross-platform scripts**: Port critical PowerShell scripts to Python for Linux compatibility.

14. **API documentation**: Auto-generate OpenAPI docs from FastAPI routes. Currently no published API spec.

15. **Dependency audit**: Review all 80 frozen packages for CVEs and update where safe.

16. **Reduce duplicate FBX files**: Same 11MB FBX exists in both `assets/avatar/` and `ui/Female Advanced V2 3D Model/`.

---

## Appendix A: File Count Summary

| Directory | Files | Subdirs | Notes |
|-----------|-------|---------|-------|
| services/ | ~250 | 80+ | Includes __pycache__ |
| scripts/ | ~110 | 10 | Operations tooling |
| tests/ | ~55 | 8 | Integration + unit |
| config/ | ~15 | 8 | Consolidated configs |
| docs/ | ~25 | 5 | Documentation |
| training/ | ~30 | 4 | ML training |
| assets/ | ~150+ | 20+ | Avatar, textures, Unity |
| models/ | ~10 | 12 | ~35GB ML weights |
| releases/ | ~25 | 5 | Release bundles |
| **Total** | **~700+** | **150+** | Excluding .git, envs |

## Appendix B: Port Assignment Map

| Port | Service | Status |
|------|---------|--------|
| 7000 | API Gateway | Active |
| 7010 | Model Router | Active |
| 7020 | Memory Engine | Active |
| 7030 | Pipecat | Active |
| 7040 | OpenClaw | Active |
| 7050 | EVA-OS | Active |
| 7060 | Vision Capture | Optional |
| 7070 | Perception | Optional |
| 8000 | Orchestrator | Separate |
| 11434 | Ollama (external) | External |

## Appendix C: Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Web Framework | FastAPI 0.116.1 |
| ASGI Server | Uvicorn 0.35.0 |
| Validation | Pydantic 2.11.7 |
| HTTP Client | httpx 0.28.1 |
| WebSocket | websockets 16.0 |
| Database | SQLite 3 (WAL mode) |
| ML Framework | PyTorch 2.10.0+cu128 |
| ML Training | Unsloth 2026.1.4, TRL 0.24.0 |
| LLM Inference | Ollama (local), Anthropic/OpenRouter (cloud) |
| ASR | faster-whisper-large-v3 |
| VLM | Qwen3-VL-32B-Instruct |
| Embeddings | Qwen3-Embedding-8B (GGUF) |
| Operating System | Windows 11 Pro |
| Shell | PowerShell 5.1 |
| Version Control | Git |
| Package Manager | pip (frozen), conda (env) |

---

**End of Analysis**

*Generated 2026-02-14 by architecture audit. Total cleanup: 252 empty directories, 48 rogue/debug files, 4 duplicate directory trees eliminated.*
