# Changelog

All notable changes to Sonia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
