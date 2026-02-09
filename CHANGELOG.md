# Changelog

All notable changes to Sonia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.0] - Unreleased (Companion Experience Layer)

### Added

#### Track A: Persona + Fine-tune Pipeline
- Dataset directory contract: `S:\datasets\{text,vision,speech}\{raw,curated,processed}` + manifests + exports
- Dataset manifest schema v1.1.0 (`datasets/manifests/schema.py`): strict key validation, provenance dataclass, SplitConfig/InvariantConfig/ExportConfig, deterministic build IDs via `compute_build_id()`
- 5-stage text processing pipeline (`pipeline/text/process.py`): normalize, dedupe, classify, split, export JSONL with deterministic output (sorted keys, explicit newlines)
- Identity invariant enforcement (`pipeline/text/identity_invariants.py`): 3 severity levels (CRITICAL/MAJOR/MINOR), 13 anchor rules with reason codes, threshold-based enforcement, `get_test_fixtures()` for testing
- Evaluation harness (`pipeline/eval/harness.py`): 5-dimension checks (consistency, verbosity, refusal, tool misuse, regression), baseline comparison with per-category deltas
- 13 seed evaluation prompts (`pipeline/eval/seed_prompts.jsonl`)
- Unified CLI (`pipeline/cli.py`): validate-manifest, process-text, enforce-invariants, export-jsonl, run-eval subcommands

#### Track B: Vision Presence
- Vision capture service on port 7060 (`services/vision-capture/main.py`)
  - RAM ring buffer (300 frames), ambient (1fps) / active (10fps) modes
  - Privacy hard gate: zero frames accepted when disabled, buffer cleared immediately
  - Explicit privacy endpoints: GET/POST privacy status/enable/disable
  - Per-category rejection counters (privacy, mode, size, rate)
  - Zero-frame invariant enforced at startup, shutdown, and on every read
- Perception pipeline on port 7070 (`services/perception/main.py`)
  - Event-driven VLM inference (wake_word, motion, user_command, scheduled triggers)
  - EventType enum + EventEnvelope model for cross-service event bus
  - Structured SceneAnalysis output with Pydantic validator enforcing `action_requires_confirmation=True`
  - Privacy check via vision-capture before any inference (fail-closed)
  - Event ingestion endpoint: POST /v1/perception/events
  - Privacy block counter + per-inference timing stats

#### Track C: Embodiment UI
- Electron + React + Three.js avatar application (`ui/sonia-avatar/`)
  - Zustand store: 5-state connection FSM (disconnected/connecting/connected/reconnecting/error), optimistic toggles with PendingControl ACK/NACK/timeout rollback, hold/interrupt/replay state, diagnostics snapshot
  - ConnectionManager: singleton WS client with exponential backoff reconnect (1s-16s cap), inbound event dispatch, outbound command envelope, ACK expiry timer
  - ControlBar: all buttons wired through ACK model, pending pulse indicator, context-aware disable (interrupt only when speaking/thinking)
  - DiagnosticsPanel: slide-out showing session, latency breakdown, breaker states, DLQ depth, vision status, last error
  - StatusIndicator: 5-state dot, reconnect counter, conversation state label, hold badge
  - 3D avatar scene with emotion-driven color, breathing animation, speaking pulse
  - Dark red/black theme, frameless window

#### Cross-Track Integration
- Unified event envelope (`services/shared/events.py`): EventType enum (20 types), EventEnvelope with auto-generated `req_XXX` correlation IDs, `derive()` for child event propagation, `validate_envelope()`
- 17 cross-track integration tests (`tests/integration/test_v26_cross_track.py`): Track A (6), Track B (6), Cross-Track (5)

#### Ops
- v2.6 promotion gate (`scripts/promotion-gate-v26.ps1`): 16 gates across 6 categories (regression, health, recovery, artifacts, observability, companion)
  - Gate 2: v2.6 cross-track test suite (17 tests)
  - Gate 4: Vision + perception service health
  - Gate 14: Vision privacy hard gate
  - Gate 15: UI doesn't block core loop
  - Gate 16: Model package checksum + rollback
  - Machine-readable JSON reports (schema v2.0) with per-gate timing and environment metadata
  - -SkipLiveServices, -SkipUI, -ReportOnly switches
- Rollback script (`scripts/rollback-to-v25.ps1`): safe rollback to v2.5.0-rc1 with -DryRun support, rollback markers, service stop/restart/health verify
- Updated `sonia-config.json` with vision_capture, perception, and companion_ui sections

## [1.0.0] - 2026-02-08

### Added

#### Core Architecture
- **EVA-OS Supervisor**: Deterministic control plane with risk-aware approval gating
  - OperationalState tracking across all system components
  - ToolCallValidator with 4-tier risk classification (TIER_0_READONLY through TIER_3_DESTRUCTIVE)
  - Scope-bound approval tokens preventing token reuse across different actions
  - S:\ root contract enforcement for all filesystem operations
  - Mode switching: conversation, operator, diagnostic, dictation, build

#### Message Contracts
- Canonical JSON envelope system for all inter-service communication
- UserTurn, SystemEvent, Plan, ToolCall, ToolResult contracts
- MemoryQuery/Result, ApprovalRequest/Response structured messages
- Enables service composability (swap Pipecat, downstream unaffected)

#### Service Microservices
- **API Gateway** (port 7000): Stable front door, UI transport, input normalization
  - Request/response validation, rate limiting, request IDs
  - Proxying to downstream services (model-router, memory-engine, pipecat, openclaw)
  - Chat, memory, tools, voice, vision, models, admin endpoints
  - Policy guard for approval workflow

- **Model Router** (port 7010): Provider/model selection and routing
  - Support for multiple LLM providers: Ollama, OpenRouter, Anthropic, LMStudio, vLLM
  - Adapter layer for chat, embeddings, reranking, vision capabilities
  - Load shedding and intelligent scheduling
  - Response caching for cost optimization

- **Memory Engine** (port 7020): Persistence, ledger, retrieval
  - Durable event ledger with causality tracking
  - Bi-temporal storage (valid_time + transaction_time)
  - Vector embeddings with semantic search
  - Forgetting/decay strategies with configurable retention
  - Document ingestion pipeline with chunking
  - Full redaction support for sensitive information

- **Pipecat** (port 7030): Real-time modality gateway
  - WebSocket-based streaming protocol
  - Voice input/output (VAD, ASR, TTS)
  - Turn-taking and barge-in handling
  - Latency optimization for sub-200ms round-trips
  - Integration with Qwen ASR/TTS and model router

- **OpenClaw** (port 7040): Action execution and governance
  - Desktop automation (mouse, keyboard, screenshot)
  - Browser control and UI automation
  - Filesystem operations with root contract enforcement
  - Terminal/shell command execution
  - Risk-tiered action policy with approval requirements
  - Audit logging of all executed actions

#### Tool Catalog
- 13 comprehensive tools across 4 risk tiers
- Filesystem tools (list, read, stat, create, write, append, move, copy, delete)
- Process tools (list, start, stop, kill)
- HTTP tools (GET requests)
- Shell tools (PowerShell scripts, arbitrary commands)
- Verification specs for proof of execution

#### Configuration Management
- Single source of truth (sonia-config.json)
- Service definitions with ports, health endpoints, logging
- Canonical root (S:\) enforced across all components
- Environment-specific configs (dev, production)
- Secrets management with schema validation

#### Operational Infrastructure
- **Startup Script** (start-sonia-stack.ps1): Launches all 5 services with health checks
- **Dependency Extraction** (setup-upstream-dependencies.ps1): Unpacks upstream sources
- **Diagnostic Tool** (doctor-sonia.ps1): 6-phase health validation
- Centralized logging to S:\logs\services\
- PID tracking to S:\state\pids\
- Port conflict detection and graceful error reporting

#### Documentation
- Complete build guide (SONIA_BUILD_GUIDE.md)
- Executive summary (BUILD_SUMMARY.txt)
- Architecture reference (README.md)
- Service contracts reference
- Memory ledger specification
- Pipecat pipeline specification
- OpenClaw action policy documentation
- Troubleshooting guide
- Local setup guide for Windows
- Release process documentation

### Technical Specifications

#### Security Model
- Risk-tiered approval workflow
- Scope-bound tokens (hash of tool_name + args)
- Root contract enforcement (S:\ boundary)
- Audit logging of all policy decisions
- Redaction of sensitive information in logs
- Environment-based secret management

#### Deployment
- Docker Compose for development and production
- Individual Dockerfiles for each service
- Windows service configuration (.xml manifests)
- Inno Setup installer for Windows distribution
- Pre/post-install scripts

#### Testing
- Unit tests for each service
- Integration tests for cross-service workflows
- Contract tests for OpenAPI compliance
- E2E tests for operator approval flow
- Playwright-based UI tests

### Infrastructure

#### Data Directories
- S:\logs\services\: Centralized service logs
- S:\logs\audit\: Audit trail of all actions
- S:\state\pids\: Process ID tracking
- S:\state\sessions\: Active session state
- S:\state\locks\: Distributed lock management
- S:\data\memory\: Memory ledger storage
- S:\data\vector\: Vector embeddings
- S:\data\uploads\: User-uploaded files
- S:\artifacts\: Build artifacts

#### Development Tools
- Makefile for common tasks
- Taskfile.yml for complex workflows
- Pre-commit hooks for code quality
- Ruff for fast Python linting
- mypy for static type checking
- pytest for unit testing
- Playwright for e2e testing

### Initial Release

This is the first official release of Sonia Final Iteration, encompassing the complete architecture, all 5 core microservices, EVA-OS supervisor, OpenClaw tool catalog, comprehensive configuration system, production-grade operational infrastructure, and full documentation.

## Unreleased

### Planned

#### Phase D: Memory Engine Enhancement
- Advanced retrieval ranking (BM25 + semantic)
- Provenance tracking with source citations
- Context-aware filtering and deduplication
- Knowledge graph construction

#### Phase E: Voice Enhancement
- Real-time streaming with sub-200ms latency
- Advanced turn-taking strategies
- Speaker identification
- Emotion detection

#### Phase F: UI Streaming and Vision
- Server-Sent Events (SSE) for streaming responses
- WebSocket for real-time updates
- Vision capture and processing
- UI element detection and interaction
- End-to-end voice + vision + action loops

#### Phase G: Advanced Governance
- Policy as Code (PAC) engine
- Fine-grained permission model
- Operator team collaboration
- Delegation and escalation workflows

#### Phase H: Analytics and Observability
- Comprehensive metrics collection
- Distributed tracing
- Cost tracking per model provider
- Usage analytics dashboards
- Performance profiling

---

**Project Created**: 2026-02-08
**Initial Build**: Phase A-H (Full architecture, core services, documentation)
**Status**: Production-ready baseline established
