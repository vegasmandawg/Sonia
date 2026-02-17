# SONIA: Complete Project Deep-Dive Report

**Document Classification**: Internal Technical Report
**Version**: 2.10.0-dev
**Report Date**: February 14, 2026
**Branch**: `v2.10-dev` (commit `bd8b764`)
**Author**: Architecture Audit System
**Format**: 11pt, single-spaced equivalent

---

## Table of Contents

1. [Genesis and Vision](#1-genesis-and-vision)
2. [Foundational Architecture Design](#2-foundational-architecture-design)
3. [The Microservices Topology](#3-the-microservices-topology)
4. [API Gateway: The Nervous System](#4-api-gateway-the-nervous-system)
5. [Model Router: Intelligence Distribution](#5-model-router-intelligence-distribution)
6. [Memory Engine: Persistent Cognition](#6-memory-engine-persistent-cognition)
7. [Pipecat: Voice as Primary Interface](#7-pipecat-voice-as-primary-interface)
8. [OpenClaw: Deterministic Desktop Autonomy](#8-openclaw-deterministic-desktop-autonomy)
9. [EVA-OS: The Supervisor Brain](#9-eva-os-the-supervisor-brain)
10. [Vision and Perception Pipeline](#10-vision-and-perception-pipeline)
11. [The Safety Architecture](#11-the-safety-architecture)
12. [Turn Pipeline: Core Cognitive Loop](#12-turn-pipeline-core-cognitive-loop)
13. [Session and Streaming Infrastructure](#13-session-and-streaming-infrastructure)
14. [Circuit Breaker and Fault Tolerance](#14-circuit-breaker-and-fault-tolerance)
15. [Memory Retrieval and Hybrid Search](#15-memory-retrieval-and-hybrid-search)
16. [The Action Pipeline](#16-the-action-pipeline)
17. [Observability and Correlation Tracing](#17-observability-and-correlation-tracing)
18. [State Management and Backup Discipline](#18-state-management-and-backup-discipline)
19. [Configuration Architecture](#19-configuration-architecture)
20. [Data Architecture and Storage](#20-data-architecture-and-storage)
21. [Machine Learning Infrastructure](#21-machine-learning-infrastructure)
22. [Training Pipeline and Fine-Tuning](#22-training-pipeline-and-fine-tuning)
23. [Avatar and Embodiment System](#23-avatar-and-embodiment-system)
24. [Testing Philosophy and Infrastructure](#24-testing-philosophy-and-infrastructure)
25. [Release Engineering and Promotion Gates](#25-release-engineering-and-promotion-gates)
26. [Development Chronology: The Six-Day Build](#26-development-chronology-the-six-day-build)
27. [Current System State Assessment](#27-current-system-state-assessment)
28. [Technical Debt Inventory](#28-technical-debt-inventory)
29. [What Remains: The Unfinished Work](#29-what-remains-the-unfinished-work)
30. [Strategic Outlook and Future Architecture](#30-strategic-outlook-and-future-architecture)

---

## 1. Genesis and Vision

SONIA -- Secure Operational Neural Interface Agent -- began as a concept for a deterministic, voice-first, local-first AI agent platform. The project's founding thesis was that existing AI assistants suffer from three fundamental weaknesses: they lack persistent memory across sessions, they cannot take reliable action on the user's behalf, and they operate without meaningful safety governance. SONIA was conceived to solve all three simultaneously.

The project's philosophical underpinning is the principle of "models propose, supervisors decide." In SONIA, no language model output directly causes side effects. Every proposed action passes through a deterministic policy layer (EVA-OS) that classifies risk, requires appropriate approval, and maintains a complete audit trail. This is not AI safety in the abstract sense -- it is operational safety for a system that controls a desktop, executes shell commands, reads and writes files, and manages voice conversations.

The initial architectural vision was codified on February 8, 2026, in three foundational documents: `ARCHITECTURE.md` (system design), `ROADMAP.md` (phased delivery from v1.0 through v2.0), and `RUNTIME_CONTRACT.md` (operational guarantees and SLAs). The roadmap originally planned a 14-month trajectory from Q1 2026 through Q2 2027, spanning six major phases (D through I). In practice, the development sprint compressed nearly the entire roadmap into six days of intensive work (February 8-14, 2026), delivering 80 commits, 10 version tags, and 580+ integration tests.

The vision document describes SONIA's end state as "the most reliable, voice-first agent platform for enterprise operations" with sub-100ms latency, 99.9% uptime, policy-as-code governance, and horizontal scaling to 10,000+ concurrent users. While the current single-machine deployment does not yet achieve all of these targets, the architectural foundations have been laid for every planned capability.

SONIA runs exclusively on Windows 11, uses Python 3.11 with FastAPI/Uvicorn for all services, and is designed for a single trusted operator. The canonical root is `S:\`, and every filesystem operation is hard-scoped to this root -- a non-negotiable security boundary enforced at multiple layers.

---

## 2. Foundational Architecture Design

SONIA follows a microservices-on-localhost pattern, a deliberate architectural choice that provides service isolation and composability without the overhead of container orchestration. All services are Python/FastAPI applications running on Uvicorn, communicating over plain HTTP on fixed ports (7000-7070). There is no service mesh, no message queue, no container runtime -- all services run as bare processes managed by PowerShell scripts.

This design embodies five core principles articulated in the architecture document:

**Deterministic Control.** EVA-OS makes all policy decisions. Language models propose actions; the supervisor decides whether to permit them. This separation ensures that the system's behavior is predictable and auditable regardless of which LLM is generating responses.

**Composability.** Every service is independently deployable and replaceable. The canonical JSON envelope contract means that any service can be swapped (e.g., replacing Pipecat's voice pipeline with a WebRTC implementation) without affecting the rest of the stack. Inter-service communication uses HTTP with correlation IDs, enabling service substitution without protocol changes.

**Observability.** Full causality tracking through correlation IDs (`req_xxx` format) that propagate across every service boundary. Every entry point generates a unique ID, every downstream call carries it, and every log entry includes it. This enables end-to-end request tracing without a distributed tracing backend.

**Safe by Default.** A four-tier risk classification system ensures that read-only operations execute instantly, low-risk modifications have a brief approval gate, medium-risk actions require explicit operator confirmation, and destructive operations demand confirmation plus a verification code. The system defaults to denial -- any action that cannot be classified is blocked.

**Local-First.** All core capabilities run on the local machine. Cloud LLM providers (Anthropic, OpenRouter) are optional enhancements, not requirements. The local Ollama instance provides full conversational capability, while the cloud providers add reasoning depth for complex tasks.

The inter-service message contract uses a canonical JSON envelope:

```json
{
  "message_id": "uuid-v4",
  "service_from": "api-gateway",
  "service_to": "model-router",
  "message_type": "chat_request",
  "timestamp": "ISO-8601",
  "body": { ... },
  "metadata": {
    "correlation_id": "req_xxx",
    "trace_id": "uuid-v4",
    "session_id": "session-xxx"
  }
}
```

This envelope structure provides service-agnostic communication, complete causality tracking, and enables downstream services to operate without knowledge of upstream implementation details.

---

## 3. The Microservices Topology

SONIA's runtime topology consists of 10 services across three tiers:

**Tier 1 -- Core Services (always running):**

| Service | Port | Role | Files |
|---------|------|------|-------|
| API Gateway | 7000 | Front door, session management, turn pipeline | 37 |
| Model Router | 7010 | LLM provider selection, routing, health tracking | 8 |
| Memory Engine | 7020 | Persistent memory, hybrid search, provenance | 18 |
| Pipecat | 7030 | Voice I/O, VAD, ASR, TTS, turn-taking | 18 |
| OpenClaw | 7040 | Desktop automation, policy-gated execution | 18 |
| EVA-OS | 7050 | Service supervision, policy enforcement, health | 7 |

**Tier 2 -- Vision Services (optional):**

| Service | Port | Role | Files |
|---------|------|------|-------|
| Vision Capture | 7060 | Camera capture, privacy gate, ring buffer | 1 |
| Perception | 7070 | VLM inference, scene analysis, event bus | 2 |

**Tier 3 -- Auxiliary Services (separate lifecycle):**

| Service | Port | Role | Files |
|---------|------|------|-------|
| Orchestrator | 8000 | Multi-step task orchestration | 2 |
| MCP Server | N/A | Claude Code integration via MCP protocol | 2 |
| Tool Service | N/A | Legacy tool registry (predates OpenClaw) | 4 |

The startup sequence is dependency-ordered: Memory Engine and Model Router boot first (no dependencies), followed by OpenClaw, then EVA-OS (which probes all upstream services), then Pipecat (depends on Model Router), and finally API Gateway (depends on all). Vision services boot last and are optional. This sequence is enforced by the canonical launcher `start-sonia-stack.ps1`.

The dependency graph reveals a hub-and-spoke pattern centered on the API Gateway. All client traffic enters through the Gateway, which fans out to Model Router (for LLM inference), Memory Engine (for context retrieval and storage), and OpenClaw (for action execution). EVA-OS sits as a cross-cutting supervisor that monitors all services and enforces policy decisions. Pipecat handles the specialized voice I/O pathway but ultimately feeds transcribed text back through the standard turn pipeline.

---

## 4. API Gateway: The Nervous System

The API Gateway is SONIA's largest and most complex service, comprising 37 Python source files totaling over 350KB of code. It serves as the stable front door for all client interactions and orchestrates the entire turn pipeline.

**Route Structure:**

The Gateway exposes five route groups:

- `/v1/turn` (POST) -- The core cognitive loop: memory recall, model chat, tool execution, memory write. This is the synchronous entry point for text-based interactions.
- `/v1/stream/{session_id}` (WebSocket) -- Real-time streaming for voice, text, and vision events. Handles audio frames, vision frames, and text messages with full session context.
- `/v1/sessions` (POST/GET/DELETE) -- Session lifecycle management with in-memory storage, 30-minute TTL, and a maximum of 100 concurrent sessions.
- `/v1/actions` (POST) and `/v1/actions/{id}/approve|deny` -- Action pipeline entry point with approval flow for guarded operations.
- `/v1/chat` (POST) -- Simple chat endpoint for quick interactions without the full turn pipeline.

**Core Modules:**

The Gateway contains 26 core modules implementing the system's most critical patterns:

The `action_pipeline.py` (37.2KB) is the single largest module, implementing the full desktop action execution pipeline with dry-run support, circuit breaker integration, dead letter queue failover, and comprehensive audit logging. It bridges the turn pipeline's tool calls to OpenClaw's executor system.

The `circuit_breaker.py` (10.6KB) implements the standard circuit breaker pattern with three states (CLOSED, OPEN, HALF_OPEN). Each desktop adapter (ctypes native, PowerShell subprocess, dry-run) has its own breaker instance. A 3-failure threshold triggers the OPEN state, and the breaker automatically probes with a single test request after a cooldown period before transitioning to HALF_OPEN.

The `tool_policy.py` (10.8KB) classifies every tool invocation into one of four risk tiers: `safe_read` (auto-execute), `guarded_low` (30-second auto-gate), `guarded_medium` (explicit approval required), and `guarded_high` (approval plus confirmation code). The classification is deterministic and based on capability name, not on LLM-generated reasoning.

The `session_manager.py` (5.7KB) manages in-memory sessions with TTL-based expiration. Sessions are not persisted -- a Gateway restart clears all active sessions. This is intentional for the current single-operator model but represents a known limitation for production deployment.

The `model_call_context.py` (8.6KB) provides cancellation support for model calls, allowing the operator to abort a long-running LLM inference without leaving orphaned requests. This was introduced in v2.8 as part of the deterministic operations milestone.

The `memory_recall_context.py` (10.0KB) enforces token budgets during memory retrieval, ensuring that context windows are not overloaded with irrelevant memories. The default budget is 2,000 tokens, configurable per request.

The `operator_session.py` (11.9KB) implements a state machine for operator interactions, tracking the lifecycle from initial connection through active conversation to graceful disconnect. This module ensures that operator state transitions are valid and that orphaned sessions are cleaned up.

The `perception_action_gate.py` (13.0KB) is the safety gate between the vision perception system and the action pipeline. It ensures that perception-triggered actions cannot bypass the normal approval workflow -- a "fail-closed" design where any error in the perception pipeline results in no action rather than an uncontrolled action.

**Client Modules:**

Three client modules handle outbound HTTP calls to downstream services:

- `router_client.py` -- Communicates with Model Router on port 7010. Supports task-type routing (chat, vision, reasoning) and passes correlation IDs.
- `memory_client.py` -- Communicates with Memory Engine on port 7020. Handles search queries, memory writes, and token budget enforcement.
- `openclaw_client.py` -- Communicates with OpenClaw on port 7040. Manages action requests and collects execution results.

---

## 5. Model Router: Intelligence Distribution

The Model Router is SONIA's intelligence distribution layer, responsible for selecting the optimal LLM provider for each request based on task type, provider health, and cost constraints.

**Provider Architecture:**

The Router supports three fully implemented providers, all using raw `httpx` HTTP clients (no vendor SDKs):

| Provider | Protocol | Models | Status |
|----------|----------|--------|--------|
| Ollama | HTTP (localhost:11434) | sonia-vlm:32b, qwen2.5:7b | Primary |
| Anthropic | HTTPS API | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 | Cloud fallback |
| OpenRouter | HTTPS API | Various via OpenRouter proxy | Cloud fallback |

The decision to use raw `httpx` instead of vendor SDKs (like the Anthropic Python SDK) was deliberate. It eliminates SDK version coupling, reduces dependency surface area, and provides full control over retry logic, timeout management, and request shaping.

**Routing Engine:**

The `routing_engine.py` (6.7KB) implements three routing policies:

- `local_only` -- Only use local Ollama models. No cloud calls permitted.
- `cloud_allowed` -- Prefer local models but fall back to cloud providers if local is unavailable or the task requires deeper reasoning.
- `provider_pinned` -- Route to a specific provider regardless of health or cost. Used for testing and debugging.

**Fallback Matrix:**

The Router defines task-specific fallback chains that cascade through providers when the primary is unavailable:

- `chat_low_latency`: sonia-vlm -> qwen2.5 (local only, fast response)
- `reasoning_deep`: claude-opus -> claude-sonnet -> sonia-vlm (cloud-first for complex reasoning)
- `vision_analysis`: sonia-vlm -> qwen3-vl -> claude-sonnet (vision-capable models)
- `tool_execution`: sonia-vlm -> claude-sonnet -> qwen2.5 (reliable tool calling)

**Health Registry:**

The `health_registry.py` (7.2KB) tracks provider health with probe-based monitoring. Each provider has a health score that degrades on failures and recovers on successful probes. Unhealthy providers enter a quarantine state and are excluded from routing until they pass three consecutive health probes.

**Budget Guard:**

The `budget_guard.py` (4.6KB) enforces token budget ceilings per request. If a model response would exceed the configured context window or cost threshold, the request is rejected or routed to a cheaper provider. This prevents runaway costs from cloud LLM calls.

**Generation Profiles:**

The `profiles.py` (11.8KB) defines six deterministic generation profiles:

1. `chat_default` -- Standard conversation (temperature 0.7, max 2048 tokens)
2. `precise_reasoning` -- Low temperature (0.2), longer context for analysis
3. `creative_generation` -- Higher temperature (0.9) for creative tasks
4. `code_generation` -- Low temperature (0.1), optimized for code
5. `tool_execution` -- Zero temperature, structured output for tool calls
6. `vision_analysis` -- Configured for multimodal input processing

---

## 6. Memory Engine: Persistent Cognition

The Memory Engine provides SONIA with persistent, searchable memory that survives across sessions, restarts, and updates. It is the foundation for SONIA's ability to recall past interactions, maintain context, and build long-term knowledge.

**Storage Architecture:**

The engine uses SQLite in WAL (Write-Ahead Logging) mode for durability, with the database at `S:\data\memory\memory.db` (currently 3.1MB). WAL mode enables concurrent reads during writes, which is critical for search performance during active conversation.

The database schema has evolved through 6 migrations:

1. `001_ledger.sql` -- Core append-only event ledger
2. `002_workspace.sql` -- Knowledge workspace for structured documents
3. `003_snapshots.sql` -- Context snapshot storage
4. `004_indexes.sql` -- Performance indexes for common query patterns
5. `005_fts.sql` -- Full-text search (FTS5) for keyword matching
6. `006_provenance.sql` -- Provenance audit log tracking data lineage

**Hybrid Search:**

The `hybrid_search.py` (6.3KB) implements the HybridSearchLayer, which combines two retrieval strategies:

- **BM25 Scoring** (`core/bm25.py`, 6.0KB) -- Classic term-frequency inverse-document-frequency ranking. Effective for keyword-exact queries like "What was the API key?" where exact token matching matters.
- **SQL LIKE Fallback** -- Pattern-based substring matching as a fallback when BM25 yields insufficient results. Queries must be literal substrings of stored content.

The hybrid approach was chosen over pure vector search because SONIA's memory corpus is relatively small (single-user, single-machine) and keyword-exact queries are common in operational contexts. Pure semantic search would miss queries that depend on exact terminology.

**Retrieval Pipeline:**

1. Query arrives at `/v1/search`
2. HybridSearchLayer runs BM25 scoring with FTS5 acceleration
3. If BM25 yields <3 results, SQL LIKE fallback executes
4. Results ranked by composite score: `relevance * 0.5 + recency * 0.3 + importance * 0.2`
5. Token budget enforced (default 2,000 tokens) -- results truncated to fit
6. Type filters applied (fact, preference, summary, observation, tool_event)
7. Provenance metadata attached to each result

**Memory Write Policy:**

The `memory_policy.py` in the API Gateway defines five memory write types:

- `raw` -- Unprocessed user/assistant turns
- `summary` -- LLM-generated summaries of conversation segments
- `vision_observation` -- Scene descriptions from perception pipeline
- `tool_event` -- Records of tool invocations and results
- `confirmation_event` -- Records of approval/denial decisions

The write policy is configured to never raise exceptions -- memory write failures are logged but do not block the turn pipeline. This design ensures that a memory engine outage degrades recall quality but does not prevent conversation.

**Memory Decay:**

The `core/decay.py` (9.3KB) implements memory decay strategies that reduce the relevance score of older memories over time. This prevents ancient context from dominating retrieval results and ensures that recent information is prioritized.

**Provenance Tracking:**

The `core/provenance.py` (4.6KB) maintains an audit log of every memory operation -- who wrote it, when, what source document it came from, and what transformations were applied. This provides full data lineage for compliance and debugging.

---

## 7. Pipecat: Voice as Primary Interface

Pipecat implements SONIA's voice-first interaction model, providing real-time voice activity detection, automatic speech recognition, text-to-speech synthesis, and intelligent turn-taking.

**Pipeline Architecture:**

The voice pipeline processes audio in a linear chain:

```
Audio In -> VAD -> ASR -> Turn Detection -> Model Router -> TTS -> Audio Out
              ^                                                |
         Barge-In <--------- Interruption --------------------+
```

**Voice Activity Detection (VAD):**

The `pipeline/vad.py` (7.5KB) implements energy-based and model-based voice activity detection. The VAD determines when the user is speaking versus when there is silence, which is the foundation for turn-taking decisions.

Configuration (from `sonia-config.json`):
- VAD hangover: 300ms (how long silence must persist before declaring end-of-speech)
- Turn finalization silence: 1000ms (how long silence must persist before finalizing a turn)

**Automatic Speech Recognition (ASR):**

The `pipeline/asr.py` (7.7KB) integrates with the locally-deployed faster-whisper-large-v3 model (2.9GB). The ASR supports streaming partial transcripts, meaning the UI can display what the user is saying in real-time before the turn is complete.

The `app/asr_client.py` (3.7KB) provides an abstraction layer that enables swapping ASR implementations (e.g., switching from Whisper to a cloud ASR service) without modifying the pipeline.

**Text-to-Speech (TTS):**

The `pipeline/tts.py` (8.0KB) generates speech from model responses. The TTS pipeline supports streaming output, meaning audio playback begins before the entire response is generated. The Qwen3-TTS-Tokenizer (682MB) provides the tokenization layer.

**Turn-Taking:**

The `app/turn_taking.py` (5.7KB) implements the algorithm that determines when the user has finished speaking and it is SONIA's turn to respond. This is more complex than simple silence detection -- it considers:
- Silence duration (configurable threshold)
- Prosodic cues (rising/falling intonation at end of utterance)
- Semantic completeness (is the sentence grammatically complete?)
- User interrupt signals (barge-in during SONIA's response)

**Interruption Handling:**

The `app/interruptions.py` (5.7KB) handles barge-in scenarios where the user begins speaking while SONIA is still responding. The system cancels TTS output within 100ms and returns to listening mode. An interrupt debounce of 150ms prevents false triggers from background noise.

**Session Management:**

Pipecat maintains its own session layer (`app/session_manager.py`, 11.4KB) that tracks voice session state, audio buffer management, and per-session configuration. Voice sessions have a maximum concurrency of 10 (configured in `sonia-config.json`).

**Watchdog:**

The `app/watchdog.py` (6.0KB) monitors voice session health and terminates stale sessions. If a session has no audio activity for a configurable timeout, the watchdog closes it and frees resources.

---

## 8. OpenClaw: Deterministic Desktop Autonomy

OpenClaw is SONIA's desktop automation service, providing deterministic, policy-governed action execution across 13 desktop capabilities.

**Capability Registry:**

| Capability | Risk Tier | Executor | Description |
|------------|-----------|----------|-------------|
| `file.read` | safe_read | file_exec | Read file contents |
| `file.write` | guarded_medium | file_exec | Write file contents |
| `shell.run` | guarded_high | shell_exec | Execute shell commands |
| `app.launch` | guarded_low | desktop_exec | Launch applications |
| `app.close` | guarded_low | desktop_exec | Close applications |
| `clipboard.read` | safe_read | desktop_exec | Read clipboard |
| `clipboard.write` | guarded_low | desktop_exec | Write to clipboard |
| `keyboard.type` | guarded_medium | desktop_exec | Type text |
| `keyboard.hotkey` | guarded_medium | desktop_exec | Send keyboard shortcuts |
| `mouse.click` | guarded_medium | desktop_exec | Click at screen coordinates |
| `window.list` | safe_read | desktop_exec | List open windows |
| `window.focus` | guarded_low | desktop_exec | Focus a window |
| `browser.open` | guarded_low | desktop_exec | Open URL in browser |

**Executor Architecture:**

Three executor implementations provide different execution strategies:

The **ctypes (native) executor** (`executors/desktop_exec.py`, 16.9KB) uses Python's ctypes library to call Win32 API functions directly. This provides sub-200ms execution for desktop operations like mouse clicks, keyboard input, and window management. The direct API access eliminates the overhead of launching subprocesses.

The **subprocess (PowerShell) executor** uses PowerShell subprocesses for operations that require system-level access or complex scripting. The SLO for this executor is p95 < 2000ms, reflecting the overhead of process creation.

The **dry-run executor** validates action requests without executing them. This is used for testing, policy validation, and the "what would happen" preview mode.

**Policy Engine:**

The `app/policy_engine.py` (17.3KB) evaluates every action request against the configured policy before execution. The engine:
1. Classifies the action into a risk tier based on capability name
2. Checks whether the tier requires approval
3. If approval required, generates a confirmation token with a 120-second TTL
4. Returns the token to the caller for operator presentation
5. On approval, validates the token (single-use, scope-bound, not expired)
6. On execution, logs the complete action with before/after state

**Confirmation Flow:**

The `app/confirmations.py` (16.4KB) manages the confirmation queue. Confirmation tokens are:
- Single-use (cannot be replayed)
- Scope-bound (the token hash includes the action name and arguments, so it cannot be used for a different action)
- Time-limited (120-second TTL, configurable)
- Per-session (limited to 10 pending confirmations per session to prevent queue flooding)

**Action Guard:**

The `app/action_guard.py` (11.7KB) provides pre-execution validation that checks:
- Is the capability registered and enabled?
- Are the action arguments valid (type checking, range checking)?
- Does the filesystem path fall within the canonical root `S:\`?
- Is the circuit breaker for this adapter in CLOSED or HALF_OPEN state?

---

## 9. EVA-OS: The Supervisor Brain

EVA-OS is SONIA's supervisory control plane -- the deterministic brain that makes policy decisions, monitors service health, and enforces operational boundaries.

**Service Supervisor:**

The `service_supervisor.py` (10.8KB) implements a five-state machine for each monitored service:

```
UNKNOWN -> STARTING -> HEALTHY -> DEGRADED -> UNHEALTHY
    ^                    ^         |          |
    +--------------------+---------+----------+
                   (recovery)
```

The supervisor performs `/healthz` probes against all registered services on a configurable interval (default 30 seconds). Each probe measures response time and validates the response payload. The state transitions are:

- **UNKNOWN -> STARTING**: Service registered but not yet probed
- **STARTING -> HEALTHY**: First successful probe
- **HEALTHY -> DEGRADED**: Probe succeeds but latency exceeds threshold (2 seconds)
- **DEGRADED -> UNHEALTHY**: Three consecutive failures or timeouts
- **UNHEALTHY -> HEALTHY**: Three consecutive successful probes (recovery)

State transitions emit events through the shared EventBus (`services/shared/event_bus.py`), enabling other services to react to health changes.

**Dependency Graph:**

EVA-OS maintains a dependency graph that defines which services depend on which others:
- API Gateway depends on: Model Router, Memory Engine, OpenClaw
- Pipecat depends on: Model Router, API Gateway
- Perception depends on: Vision Capture, Model Router

When a service transitions to UNHEALTHY, EVA-OS checks the dependency graph and marks dependent services as DEGRADED. This cascading health model provides early warning of systemic issues.

**Policy Enforcement:**

EVA-OS enforces the root contract (`S:\` filesystem boundary) and the risk-tiered approval workflow. All policy decisions are logged with full context for audit compliance.

**Orchestration:**

The `app/orchestrator.py` (10.2KB) provides basic multi-step task orchestration, coordinating sequences of actions that span multiple services. However, the separate Orchestrator service on port 8000 (`services/orchestrator/`) provides more sophisticated multi-step planning and is the intended future home for complex orchestration logic.

---

## 10. Vision and Perception Pipeline

The vision and perception pipeline was introduced in Stage 4 (multimodal) and hardened through v2.6 (companion experience) and v2.8 (deterministic operations).

**Vision Capture (Port 7060):**

The Vision Capture service manages camera input with a privacy-first design:

- **Privacy Hard Gate**: Vision is disabled by default (`default_mode: "off"`). It must be explicitly enabled per session via `control.vision.enable` WebSocket events. There is no ambient capture without explicit operator consent.
- **Ring Buffer**: A 300-frame circular buffer stores recent frames for context. Old frames are overwritten, preventing unbounded memory growth.
- **Resolution Modes**: Two capture modes -- Ambient (320x240 @ 1fps for passive awareness) and Active (640x480 @ 10fps for detailed analysis).
- **Frame Limits**: Maximum 1MB per frame, 10fps rate limit, 3 frames per turn. Invalid or oversized frames are rejected non-fatally.
- **Zero-Frame Guarantee**: If vision is disabled, the service guarantees zero frames are captured or stored. This is verified by integration tests.

**Perception (Port 7070):**

The Perception service runs VLM (Vision-Language Model) inference on captured frames:

- **VLM Inference**: Uses the locally-deployed Qwen3-VL-32B-Instruct model for real-time scene understanding. As of v2.10, this is real inference (not stubbed).
- **Event Bus Integration**: Receives `perception.trigger` events and emits `perception.result` events through the shared event system.
- **Scene Analysis**: Produces structured `SceneAnalysis` output that describes what is visible, what has changed, and what actions might be relevant.
- **Confirmation Enforcement**: Scene analysis results that recommend actions must pass through the standard confirmation workflow. The perception pipeline cannot bypass the safety gate.
- **Fail-Closed Design**: Any error in the inference pipeline returns a safe default (empty analysis, no recommended actions) rather than an uncontrolled output.

**Perception-Action Gate:**

The `perception_action_gate.py` (13.0KB) in the API Gateway ensures that perception-triggered actions are bypass-proof. Even if the VLM suggests an action, it must pass through the same risk classification, approval, and audit pipeline as any other action. This prevents the vision system from becoming an uncontrolled automation pathway.

---

## 11. The Safety Architecture

SONIA's safety architecture is a multi-layered defense-in-depth system designed to prevent unintended side effects from AI-generated actions.

**Layer 1 -- Trust Boundaries:**

```
UNTRUSTED: Client input, LLM outputs, external APIs
    | (validated, sanitized)
TRUSTED: API Gateway, EVA-OS (policy layer)
    | (policy-checked, approval tokens)
TRUSTED: Model Router, Memory Engine, Pipecat
    | (approval token verified)
EXECUTION: OpenClaw (action execution with audit)
```

All LLM outputs are treated as untrusted input. The API Gateway validates and sanitizes model responses before passing them to the action pipeline. This includes stripping control characters (C0 chars), enforcing output length limits (max_output_chars=4000), and rejecting empty responses.

**Layer 2 -- Risk Classification:**

Every tool invocation is classified into one of four tiers:

| Tier | Label | Approval | Timeout | Examples |
|------|-------|----------|---------|----------|
| 0 | safe_read | Auto-execute | None | file.read, window.list |
| 1 | guarded_low | 30s auto-gate | 30s | app.launch, browser.open |
| 2 | guarded_medium | Explicit approval | 5min | file.write, keyboard.type |
| 3 | guarded_high | Approval + code | 5min | shell.run, filesystem.delete |

The classification is based on the capability name, not on the LLM's assessment of risk. This ensures that a compromised or hallucinating model cannot escalate its own privileges.

**Layer 3 -- Root Contract:**

All filesystem operations are hard-scoped to `S:\`. This is enforced at three independent layers:
1. EVA-OS policy layer rejects paths outside the root
2. OpenClaw file executor validates paths before execution
3. API Gateway action pipeline performs pre-checks

A path traversal attack (e.g., `S:\..\..\Windows\System32\`) would need to bypass all three layers to succeed.

**Layer 4 -- Approval Tokens:**

Approval tokens are cryptographic, single-use, scope-bound, and time-limited:
```
scope_hash = HMAC-SHA256(tool_name + "|" + args_json, key)
token = {
  scope_hash: scope_hash,
  expires_at: now + 120s,
  approval_code: random_6_digit
}
```

The scope hash ensures that a token approved for `file.read("config.json")` cannot be reused for `file.write("config.json")`. The 120-second TTL prevents stale approvals from being exploited later.

**Layer 5 -- Audit Trail:**

Every action, approval, and denial is logged to `S:\logs\gateway\actions.jsonl` with full context: who requested it, what was approved, what was executed, and what the result was. The dead letter queue (`dead_letter.py`) captures failed actions for later analysis and optional replay.

---

## 12. Turn Pipeline: Core Cognitive Loop

The turn pipeline is SONIA's core cognitive loop, implementing the sequence: **memory recall -> model chat -> tool execution -> memory write**.

**Step 1: Memory Recall**

When a turn request arrives at `/v1/turn`, the Gateway first queries the Memory Engine for relevant context. The `memory_recall_context.py` enforces a token budget (default 2,000 tokens) to prevent context window overflow. The retrieval pipeline returns memories ranked by a composite score of relevance, recency, and importance, with type filters to prefer summaries over raw turns.

**Step 2: Model Chat**

The recalled memories are injected into the model prompt as system context. The Gateway calls the Model Router (`/v1/chat`), which selects the optimal provider based on the routing policy and task type. The `model_call_context.py` wraps this call with cancellation support -- the operator can abort a long-running inference without waiting for completion.

**Step 3: Tool Execution**

If the model response contains tool calls, the Gateway classifies each one through `tool_policy.py`, obtains approval if required, and executes the action through the action pipeline. The circuit breaker protects against adapter failures, and the dead letter queue captures any failed actions.

**Step 4: Memory Write**

After the turn completes, the Gateway writes the conversation context to Memory Engine according to `memory_policy.py`. Five write types are used: raw turns, summaries, vision observations, tool events, and confirmation events. The write policy never raises exceptions -- a failing Memory Engine degrades recall quality but does not block conversation.

**Quality Controls:**

The `turn_quality.py` (2.1KB) applies response normalization:
- Strip C0 control characters from model output
- Enforce maximum output length (4,000 characters)
- Reject empty responses with a fallback cascade
- Add quality annotations: `generation_profile_used`, `fallback_used`, `tool_calls_attempted/executed`, `completion_reason`

**Latency Instrumentation:**

Every turn records six latency measurements:
- `memory_read_ms` -- Time to retrieve context from Memory Engine
- `model_ms` -- Time for LLM inference
- `tool_ms` -- Time for tool execution (if applicable)
- `memory_write_ms` -- Time to persist the turn
- `asr_ms` -- Time for speech recognition (voice turns only)
- `vision_ms` -- Time for vision processing (multimodal turns only)
- `total_ms` -- End-to-end turn latency

These measurements are logged to `S:\logs\gateway\turns.jsonl` and used by soak tests to verify SLO compliance.

---

## 13. Session and Streaming Infrastructure

**Session Lifecycle:**

Sessions are created via `POST /v1/sessions` and managed in-memory by `session_manager.py`. Each session tracks:
- Session ID (UUID)
- Creation timestamp
- Last activity timestamp
- Session configuration (model, voice profile, vision settings)
- Turn history (for context continuity)
- Pending confirmation tokens (max 10 per session)

Sessions expire after 30 minutes of inactivity (TTL configurable). The maximum concurrent session count is 100, enforced at creation time.

**WebSocket Streaming:**

The `routes/stream.py` (25.3KB) implements WebSocket streaming for real-time interactions:

- **Text messages**: Sent/received as JSON with event type classification
- **Audio frames**: Binary audio data for voice I/O
- **Vision frames**: Base64-encoded image frames from camera
- **Control events**: Session control (vision enable/disable, mode changes)
- **Correlation IDs**: Every WebSocket message carries a correlation ID for tracing

The streaming protocol supports three event families:
1. `input.*` -- Client-to-server events (text, audio, vision frames)
2. `output.*` -- Server-to-client events (responses, audio, status)
3. `control.*` -- Bidirectional control events (vision toggle, session config)

**UI Streaming:**

The `routes/ui_stream.py` (15.6KB) provides a specialized streaming endpoint optimized for the companion UI. It handles the Zustand state management protocol with ACK-based message delivery (optimistic updates with rollback on failure).

---

## 14. Circuit Breaker and Fault Tolerance

SONIA implements a comprehensive fault tolerance strategy centered on the circuit breaker pattern.

**Circuit Breaker:**

The `circuit_breaker.py` (10.6KB) implements per-adapter circuit breakers with three states:

| State | Behavior |
|-------|----------|
| CLOSED | Normal operation, failures counted |
| OPEN | All requests rejected immediately, cooldown timer running |
| HALF_OPEN | Single probe request allowed, success -> CLOSED, failure -> OPEN |

Configuration:
- Failure threshold: 3 consecutive failures trigger OPEN
- Cooldown period: 30 seconds before transitioning to HALF_OPEN
- Probe limit: 1 request in HALF_OPEN state
- Metrics: Time-series event tracking (bounded to 200 events)

Each desktop adapter (ctypes, subprocess, dry-run) has its own breaker instance, so a failure in PowerShell subprocess execution does not block native ctypes operations.

**Dead Letter Queue:**

The `dead_letter.py` (6.2KB) captures failed action executions for later analysis. Each dead letter contains:
- Original action request
- Failure reason and stack trace
- Timestamp and correlation ID
- Retry eligibility classification

Dead letters can be replayed via `POST /v1/dead-letters/{id}/replay`, with an optional `?dry_run=true` parameter to validate the replay without side effects.

**Retry Taxonomy:**

The `retry_taxonomy.py` (4.5KB) classifies failures into 8 categories, each with a specific retry policy:

| Class | Retryable | Backoff | Examples |
|-------|-----------|---------|----------|
| CONNECTION_BOOTSTRAP | Yes | Exponential | Service not yet started |
| TIMEOUT | Yes | Linear | Slow model inference |
| CIRCUIT_OPEN | No | Wait for cooldown | Adapter breaker tripped |
| POLICY_DENIED | No | N/A | Action blocked by policy |
| VALIDATION_FAILED | No | N/A | Invalid action arguments |
| EXECUTION_ERROR | Maybe | Exponential | Runtime error in executor |
| BACKPRESSURE | Yes | Exponential | Too many concurrent actions |
| UNKNOWN | No | N/A | Unclassified failures |

**Health Supervisor:**

The `health_supervisor.py` (8.6KB) monitors the health of all downstream services from the Gateway's perspective. It performs periodic probes and updates internal health state, which feeds into routing decisions and circuit breaker management.

---

## 15. Memory Retrieval and Hybrid Search

The Memory Engine's retrieval system is one of SONIA's most architecturally significant components, combining multiple search strategies for optimal recall.

**BM25 Implementation:**

The `core/bm25.py` (6.0KB) implements the Okapi BM25 ranking algorithm, which scores documents based on term frequency, inverse document frequency, and document length normalization. BM25 is effective for queries where exact keyword matching is important, such as searching for specific names, identifiers, or technical terms.

The implementation uses SQLite's FTS5 (Full-Text Search) extension for efficient tokenization and inverted index maintenance. FTS5 handles stemming, stop-word elimination, and Unicode normalization.

**HNSW Vector Index:**

The `vector/hnsw_index.py` (12.3KB) implements an HNSW (Hierarchical Navigable Small World) graph for approximate nearest-neighbor search on dense vector embeddings. The HNSW index enables semantic search -- finding memories that are conceptually related even if they do not share keywords.

The embeddings are generated by the Qwen3-Embedding-8B model (15.1GB, GGUF format), producing high-dimensional vectors for each memory entry.

**Current limitation**: The HNSW index exists only in memory and must be rebuilt on every service restart. For the current corpus size (single-user, months of interaction), rebuild time is acceptable, but this will not scale to larger deployments.

**Hybrid Ranking:**

The HybridSearchLayer combines BM25 and vector search results using a weighted composite score:
```
final_score = relevance * 0.5 + recency * 0.3 + importance * 0.2
```

Where `relevance` is the search-method score (BM25 or cosine similarity), `recency` is a time-decay factor favoring recent memories, and `importance` is a per-entry weight set during memory writes (e.g., confirmed facts are weighted higher than casual observations).

**Sentence-Level Chunking:**

The `core/chunker.py` (7.1KB), introduced in v2.10, implements sentence-level text chunking for document ingestion. Previous versions used fixed-size character chunks, which frequently split sentences mid-thought. The new chunker preserves sentence boundaries, producing more coherent memory entries.

**Reranking:**

The Qwen3-Reranker-8B model (16.4GB, GGUF format) provides optional reranking of search results. After the initial retrieval produces a candidate set, the reranker scores each candidate against the original query for improved precision.

---

## 16. The Action Pipeline

The action pipeline (`action_pipeline.py`, 37.2KB) is the largest single module in the codebase and implements the complete lifecycle of desktop action execution.

**Pipeline Stages:**

1. **Validation**: Action request parsed and validated against capability registry
2. **Policy Check**: Risk tier classification and approval requirement determination
3. **Approval Gate**: If required, confirmation token minted and returned to caller
4. **Token Validation**: On approval receipt, token verified (scope, expiry, single-use)
5. **Adapter Selection**: Choose executor (ctypes, subprocess, dry-run) based on capability
6. **Breaker Check**: Verify circuit breaker state for selected adapter
7. **Execution**: Run the action through the selected executor
8. **Result Capture**: Collect execution result, timing, and state changes
9. **Audit Log**: Write complete action record to audit trail
10. **Dead Letter**: On failure, capture to dead letter queue with retry classification

**Dry-Run Mode:**

Every action supports a `dry_run=true` flag that executes steps 1-4 (validation through token) without actually performing the action. This enables "what would happen" previews and testing.

**Telemetry:**

The `action_telemetry.py` (4.3KB) instruments every action with timing data:
- `queue_ms` -- Time waiting in execution queue
- `validation_ms` -- Time for argument validation
- `policy_ms` -- Time for policy evaluation
- `execution_ms` -- Time for actual execution
- `total_ms` -- End-to-end action latency

**SLO Budgets:**

Each adapter has a defined SLO budget:
- Native ctypes: p95 < 200ms
- PowerShell subprocess: p95 < 2000ms
- Dry-run: p95 < 2000ms

Soak tests (`soak_stage5_actions.ps1`, `soak_stage6_latency.ps1`) verify these SLOs under sustained load.

---

## 17. Observability and Correlation Tracing

SONIA's observability stack provides full causality tracking across all service boundaries without requiring a distributed tracing backend.

**Correlation IDs:**

Every entry point (HTTP request, WebSocket connection) generates a unique correlation ID in the format `req_xxx`. This ID propagates to all downstream service calls via the `X-Correlation-ID` HTTP header. All log entries include the correlation ID, enabling end-to-end request tracing by grepping log files.

Stage 7 identified and fixed 5 gaps in correlation ID propagation across `stream.py` and `main.py`, ensuring complete coverage.

**Structured Logging:**

All services log to JSONL (JSON Lines) format:

| Log File | Content |
|----------|---------|
| `logs/gateway/turns.jsonl` | Complete turn records with latency |
| `logs/gateway/sessions.jsonl` | Session lifecycle events |
| `logs/gateway/actions.jsonl` | Action execution audit trail |
| `logs/gateway/errors.jsonl` | Error events with correlation IDs |
| `logs/gateway/dead_letters.jsonl` | Dead letter queue entries |
| `logs/services/model-router/routes.jsonl` | Routing decisions with provider selection |
| `logs/services/*.out.log` | Service stdout (JSON format) |
| `logs/services/*.err.log` | Service stderr (text format) |

**Diagnostics Endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/diagnostics/snapshot` | Full system state dump |
| `GET /v1/breakers/metrics` | Circuit breaker event history |
| `GET /v1/backups` | List state backups |
| `GET /v1/backups/verify` | Verify backup integrity (SHA-256) |

**Incident Bundle Export:**

The `scripts/export-incident-bundle.ps1` exports a complete incident investigation package:
- Service logs for a configurable time window (default 15 minutes)
- Health check results for all services
- Circuit breaker state and history
- Dead letter queue contents
- System diagnostics snapshot
- Git revision and configuration snapshot

---

## 18. State Management and Backup Discipline

**State Backup System:**

The `state_backup.py` (9.0KB) provides automated state backup and restore with SHA-256 integrity verification.

Each backup snapshot (stored in `S:\backups\state\`) contains:
- `actions.json` -- Executed action history
- `breakers.json` -- Circuit breaker state (per-adapter)
- `dead_letters.json` -- Dead letter queue contents
- `manifest.json` -- SHA-256 checksums for all files

14 timestamped backups exist as of this report.

**Backup API:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/backups` | POST | Create new backup snapshot |
| `/v1/backups` | GET | List all available backups |
| `/v1/backups/verify` | GET | Verify latest backup integrity |
| `/v1/restore/dlq` | POST | Restore dead letter queue from backup |

**Integrity Verification:**

Backups are verified by recomputing SHA-256 hashes of all files and comparing against the manifest. Any hash mismatch indicates corruption or tampering.

---

## 19. Configuration Architecture

SONIA uses a dual-format configuration system that is one of its known architectural debts.

**Canonical Configuration:**

`S:\config\sonia-config.json` (227 lines) is the primary configuration file. It contains:
- Service definitions (port, host, health endpoint for all 8 services)
- Model configuration (5 models with context windows and latency targets)
- Voice configuration (sample rate, VAD, turn-taking, barge-in)
- UI configuration (window size, theme, WebSocket reconnect)
- Companion configuration (persona, vision, embodiment)

**YAML Configuration:**

Several YAML files provide supplementary configuration:
- `config/app.yaml` -- Application-level settings
- `config/ports.yaml` -- Port assignments
- `config/logging.yaml` -- Log formatters and handlers
- `config/policies.yaml` -- EVA-OS tier policies
- `config/runtime.yaml` -- Runtime parameters
- `config/models/model-routing.yaml` -- Model routing rules
- `config/services/services.yaml` -- Service definitions
- `config/voice/voice-profile.yaml` -- Voice profile settings
- `config/policies/default.yaml` -- Default policy configuration

**Configuration Conflicts:**

Three known conflicts exist:
1. `app.yaml` references `/health` endpoints; the canonical contract specifies `/healthz`
2. `app.yaml` references `S:\configs` (pre-cleanup path); should be `S:\config`
3. `sonia-config.json` references `S:\shared\schemas` (pre-cleanup); should be `S:\config\schemas`

**Dependency Locking:**

`S:\config\dependency-lock.json` provides SHA-256 hashes for all frozen dependencies. The root-level `requirements-frozen.txt` lists 80 packages with exact version pins, including PyTorch 2.10.0+cu128, FastAPI 0.116.1, and websockets 16.0.

---

## 20. Data Architecture and Storage

**Memory Database:**

| Store | Technology | Location | Size |
|-------|-----------|----------|------|
| Event Ledger | SQLite (WAL) | `S:\data\memory\memory.db` | 3.1MB |
| Vector Index | HNSW (in-memory) | Runtime only | Variable |
| Sessions | JSON files | `S:\data\sessions\` | 458 files (233B each) |

The SQLite database uses Write-Ahead Logging for concurrent read/write access. The schema supports ACID transactions, ensuring that memory writes are durable and consistent.

**ML Model Storage:**

| Model | Purpose | Size | Format |
|-------|---------|------|--------|
| faster-whisper-large-v3 | ASR | 2.9GB | CTranslate2 |
| Qwen3-Embedding-8B | Embeddings | 15.1GB | GGUF (f16) |
| Qwen3-Reranker-8B | Reranking | 16.4GB | GGUF (f16) |
| Qwen3-TTS-Tokenizer-12Hz | TTS tokenization | 682MB | SafeTensors |
| Qwen3-VL-32B-Instruct | VLM (base) | ~20GB | SafeTensors |
| Sonia-Qwen3-VL-32B | VLM (fine-tuned) | ~20GB | SafeTensors |
| Qwen3-14B-Claude-4.5-Opus_Mid-brain | LLM | ~14GB | SafeTensors |

Total ML model storage: approximately 35GB.

**State Management:**

Runtime state is stored in `S:\state\`:
- Process IDs for running services
- Lock files for concurrent access control
- Session state (symlinked to `S:\data\sessions\`)

**Log Storage:**

Logs are stored in `S:\logs\` with service-level separation:
- `logs/services/` -- One `.out.log` and `.err.log` per service
- `logs/gateway/` -- JSONL structured logs for turns, sessions, actions, errors

---

## 21. Machine Learning Infrastructure

SONIA's ML infrastructure spans local inference, cloud fallback, and fine-tuning capabilities.

**Local Inference Stack:**

The local inference stack is built on Ollama, which serves locally-deployed models via an OpenAI-compatible HTTP API on port 11434. The primary model is `sonia-vlm:32b`, a fine-tuned version of Qwen3-VL-32B trained on SONIA-specific data.

**GGUF Conversion Pipeline:**

The `tools/llama.cpp/` directory contains conversion tools from llama.cpp:
- `convert_hf_to_gguf.py` (564KB) -- Converts HuggingFace models to GGUF format for Ollama deployment
- `convert_lora_to_gguf.py` (20.6KB) -- Converts LoRA adapters to GGUF format

**Embedding and Reranking:**

The embedding pipeline uses Qwen3-Embedding-8B (15.1GB GGUF) for generating dense vector representations of text. These embeddings power the semantic search component of the hybrid retrieval system.

The reranking pipeline uses Qwen3-Reranker-8B (16.4GB GGUF) for re-scoring search results against the original query, improving precision for the top-k results.

**GPU Requirements:**

The ML stack requires a CUDA 12.8-compatible GPU (PyTorch 2.10.0+cu128). The combined VRAM requirement for running the VLM, embedding model, and ASR model simultaneously exceeds 24GB, suggesting that production deployment requires at least an NVIDIA RTX 4090 or equivalent.

---

## 22. Training Pipeline and Fine-Tuning

SONIA includes a complete training pipeline for fine-tuning models on domain-specific data.

**RunPod Training Infrastructure:**

The `training/runpod/` directory contains the tools for cloud-based fine-tuning:

- `train_sonia_qwen3vl.py` -- Fine-tune Qwen3-VL-32B on SONIA conversation data using Unsloth for optimization
- `setup_and_train.sh` -- RunPod instance setup script
- `combine_datasets.py` / `combine_datasets_v2.py` -- Dataset preparation and combination
- `merge_push_sharded.py` -- Merge LoRA weights into base model and push to HuggingFace (sharded for large models)
- `merge_streaming.py` -- Memory-efficient streaming merge for constrained environments
- `quantize_gguf.py` / `quantize_gguf_v2.py` -- GGUF quantization for local deployment

**Training Data:**

| File | Size | Purpose |
|------|------|---------|
| `sonia_combined_train.jsonl` | 7.8MB | Training split |
| `sonia_combined_val.jsonl` | 526KB | Validation split |
| `sonia_combined_test.jsonl` | 579KB | Test split |

The training data is in JSONL format with conversation turns formatted for instruction fine-tuning.

**HuggingFace Publishing:**

The `training/hf-release/` directory provides tools for publishing trained models:
- `upload_release.py` -- Upload model weights to HuggingFace Hub
- `verify_hub.py` -- Verify the uploaded model matches local checksums
- `tag_release.py` -- Create a release tag on the HuggingFace repository

**Persona Pipeline:**

The `pipeline/` directory implements a persona management system:
- `cli.py` -- CLI with 5 subcommands: `build`, `validate`, `eval`, `compare`, `export`
- `text/identity_invariants.py` -- 13 identity anchors (core personality traits) with 3 severity levels (critical, important, suggested)
- `eval/harness.py` -- 5-dimensional evaluation harness measuring persona consistency across: tone, knowledge, boundaries, style, and values
- Schema v1.1.0 with deterministic build IDs for reproducible persona artifacts

---

## 23. Avatar and Embodiment System

SONIA's avatar system provides visual embodiment through a high-quality 3D female character model.

**Source Assets:**

The primary 3D model is the Female Advanced V2 3D Model, stored in both `assets/avatar/` and `ui/Female Advanced V2 3D Model/`. The model includes:
- FBX mesh files (11MB)
- 70+ high-resolution texture maps (8K-16K resolution) for diffuse color, normal maps, specular maps, subsurface scattering, ambient occlusion, and material masks
- 26 HDR environment maps for realistic lighting
- 5 IES light profiles for photographic lighting
- 43 preview renders demonstrating various poses and configurations

**Blender Integration:**

13 Blender Python scripts in `scripts/blender_*.py` provide:
- `blender_render_femadv.py` (38KB) -- High-quality rendering pipeline
- `blender_animate_femadv.py` (26KB) -- Animation system
- `blender_customize_sonia.py` (26KB) -- Material and appearance customization
- Various diagnostic scripts for bones, materials, and scene analysis

A customized Blender file (`FemAdv_Sonia.blend`) contains the SONIA-specific version of the character with tailored materials and rigging.

**Unity Integration:**

The `assets/avatar/My project/` contains a Unity project with:
- `AIAnimationController.cs` -- AI-driven animation controller
- `AIProceduralAnimator.cs` -- Procedural motion generation
- `RealtimeMotionGenerator.cs` -- Real-time motion for lip sync and gesture
- `VideoRecorder.cs` -- Video capture for avatar output
- ML Agents training configuration for learned animation behaviors

**Live Avatar Model:**

The `assets/avatar/Live-Avatar/` directory contains a HuggingFace LiveAvatar model (1.35GB SafeTensors) for real-time avatar animation driven by audio input. This model generates facial expressions and lip movements synchronized to SONIA's TTS output.

**Web Viewer:**

The `ui/sonia-avatar/` directory contains a React/Three.js web viewer prototype:
- Components: ChatPanel, ControlBar, DiagnosticsPanel, ErrorBoundary, StatusIndicator
- Three.js scene: AvatarScene with 3D model rendering
- TypeScript source with Vite build system

---

## 24. Testing Philosophy and Infrastructure

SONIA employs a testing philosophy that emphasizes integration tests over unit tests, reflecting the microservices architecture where most bugs manifest at service boundaries rather than within individual modules.

**Test Distribution:**

| Suite | Files | Approx Tests | Location |
|-------|-------|-------------|----------|
| Integration (core) | 41 | ~400+ | `tests/integration/` |
| Model Router | 4 | ~40 | `tests/model_router/` |
| Pipecat | 3 | ~30 | `tests/pipecat/` |
| Safety | 2 | ~20 | `tests/safety/` |
| Memory Engine | 2 | ~15 | `services/memory-engine/tests/` |
| Service Contracts | 5 | ~75 | `services/*/test_contract.py` |
| **Total** | **57** | **~580+** | |

**Test Naming Convention:**

Tests follow version-prefixed naming that maps directly to development stages:
- `test_turn_pipeline.py` -- Stage 2 core pipeline (8 tests)
- `test_session_lifecycle.py` -- Stage 3 sessions (5 tests)
- `test_v26_*.py` -- v2.6 companion experience (multiple files)
- `test_v27_*.py` -- v2.7 action execution (7 files)
- `test_v28_*.py` -- v2.8 deterministic operations (5 files)
- `test_v29_*.py` -- v2.9 system closure (4 files)

**Compatibility Tests:**

Stage-level compatibility tests ensure that new features do not break existing functionality:
- `test_stage2_compat.py` (7 tests) -- Verifies Stage 2 turn pipeline still works
- `test_stage3_compat.py` (7 tests) -- Verifies Stage 3 sessions still work
- `test_stage4_compat.py` (7 tests) -- Verifies Stage 4 multimodal still works

**Smoke Tests:**

Quick validation scripts that verify basic service health:
- `smoke_turn.ps1` -- Turn pipeline smoke test
- `smoke_stage3_voice.ps1` -- Voice session smoke test
- `smoke_stage4_multimodal.ps1` -- Multimodal pipeline smoke test (16 checks including regression)

**Soak Tests:**

Long-running stress tests that verify sustained performance:
- `soak_stage3_sessions.ps1` -- Session lifecycle stress (configurable sessions x turns)
- `soak_stage4_multimodal.ps1` -- Multimodal pipeline stress
- `soak_stage5_actions.ps1` -- Action throughput (200+ actions)
- `soak_stage6_latency.ps1` -- SLO compliance (240 actions, per-capability p50/p95/p99)
- `soak_v28_rc1.ps1` -- v2.8 comprehensive soak (700 operations)

**Chaos Tests:**

The `test_stage7_chaos_recovery.py` (15 tests) validates recovery from failure scenarios:
- Adapter timeout injection
- Circuit breaker trip and recovery
- DLQ replay under load
- Correlation ID survival through failures
- RTO (Recovery Time Objective) verification (target <60s, actual <1s)
- Service restart recovery

**Known Flaky Tests:**

Three flaky test patterns are documented in `issues/`:
- `INFRA-FLAKY-CHAOS-TIMING.md` -- Timing-sensitive chaos tests under load
- `INFRA-FLAKY-OLLAMA-TIMEOUT.md` -- Ollama cold-start timeouts
- `INFRA-FLAKY-WS-RACE.md` -- WebSocket race conditions in rapid connect/disconnect

---

## 25. Release Engineering and Promotion Gates

SONIA has a mature release engineering discipline with promotion gates, soak tests, and SHA-256 artifact manifests.

**Release History:**

| Version | Tag | Date | Commits | Key Features |
|---------|-----|------|---------|-------------|
| RC1 | `RC1-20260208` | Feb 8 | 1 | Initial baseline after repair |
| v2.5.0-stage5 | `v2.5.0-stage5` | Feb 8 | ~15 | Action pipeline + desktop adapters |
| v2.5.0-rc1 | `v2.5.0-rc1` | Feb 8 | ~20 | Reliability hardening, release discipline |
| v2.5.0 GA | `v2.5.0` | Feb 9 | ~25 | Observability, recovery drills |
| v2.6.0 | `v2.6.0` | Feb 9 | ~35 | Companion experience layer |
| v2.7.0 | `v2.7.0` | Feb 10 | ~40 | Companion runtime integration |
| v2.8.0-rc1 | `v2.8.0-rc1` | Feb 10 | ~45 | Deterministic operations (104 tests) |
| v2.8.0 GA | `v2.8.0` | Feb 10 | ~50 | GA artifacts (52 hardening tests) |
| v2.9.0 | `v2.9.0` | Feb 11 | ~55 | System closure |
| v2.9.1 | `v2.9.1` | Feb 12 | ~60 | Legacy test isolation |
| v2.9.2 | `v2.9.2` | Feb 13 | ~70 | Legacy closure, schema freeze |
| v2.10.0-dev | HEAD | Feb 13-14 | 80 | VLM inference, chunker, MCP |

**Promotion Gate Evolution:**

| Version | Script | Gates | Pass Rate |
|---------|--------|-------|-----------|
| v2.5.0 | `promotion-gate.ps1` | 6 | 6/6 |
| v2.5.0-rc1 | `promotion-gate-v2.ps1` | 12 | 12/12 |
| v2.6 | `promotion-gate-v26.ps1` | 16 | 16/16 |
| v2.8 | `promotion-gate-v28.ps1` | 14 | 12/14 (2 skipped live) |
| v2.9 | `promotion-gate-v29.ps1` | 12 | 12/12 |

The promotion gate concept evolved significantly over the project's lifetime. The initial 6-gate system checked only basic regression and health. By v2.6, the gate included 16 checks spanning schema validation, per-gate timing, JSON machine-readable reports, chaos test results, backup integrity, diagnostics, correlation tracing, rollback verification, and incident bundle generation.

**Release Bundle Contents:**

Each release in `S:\releases\v*.*.*\` contains:
- `release-manifest.json` -- SHA-256 checksums for all release artifacts
- `gate-report.json` -- Promotion gate results (machine-readable)
- `dependency-lock.json` -- Frozen dependency hashes
- `requirements-frozen.txt` -- Exact package versions
- `CHANGELOG.md` or `CHANGELOG.txt` -- Version-specific changes
- `soak-report.json` -- Soak test results (when applicable)
- `env/` -- Environment snapshots (conda-list, pip-freeze)

**Rollback Scripts:**

| Script | Target | Features |
|--------|--------|----------|
| `rollback-to-stage5.ps1` | v2.5.0-stage5 | DryRun support |
| `rollback-to-v25.ps1` | v2.5.0 GA | Markers, health verify |

---

## 26. Development Chronology: The Six-Day Build

SONIA's development history is remarkable for its velocity. The entire system was built in approximately six days (February 8-14, 2026), accumulating 80 git commits, 10 version tags, and 580+ integration tests.

**Day 1 (February 8): Foundation Sprint**

The project began with the RC1 baseline commit (`df0e107`) establishing the core microservices architecture after a repair operation. Within the same day, six major feature branches were merged:

- Voice pipeline infrastructure (Pipecat): 5 commits implementing deterministic turn state machine, cancel-aware interrupts, stage watchdog, latency tracking, and 32 unit tests
- Action safety layer: 4 commits adding policy engine, confirmation flow, and action guard
- Model Router profiles: 6 commits implementing routing engine, health registry, budget guard, route audit, and 4 test suites
- Stage 4 (multimodal): Release tag `v2.4.0-stage4`
- Stage 5 (action pipeline): 4 milestone commits, tag `v2.5.0-stage5`
- Stage 6 (reliability): Tag `v2.5.0-rc1`

**Day 2 (February 9): Observability and Companion**

- Stage 7 observability: 5 milestone commits (correlation tracing, incident bundle, chaos suite, backup/restore, release automation v2)
- v2.5.0 GA release with ops drill and release decision record
- v2.6 companion experience layer: 9 commits implementing persona manifests, vision capture, perception services, UI control ACK model, and the shared event envelope system
- v2.6 GA promotion

**Day 3 (February 10): Deterministic Operations**

- v2.7 companion runtime integration: 5 milestones, 92 tests
- v2.7.0 GA with contract freeze
- v2.8.0-rc1: 4 milestones (model routing cancellation, memory integration, perception gate, operator UX) with 104 tests
- v2.8.0 GA: 52 hardening tests, cleanroom verification

**Day 4 (February 11): System Closure**

- v2.9.0 system closure: Anthropic + OpenRouter providers fully implemented, EVA-OS real supervision, hybrid memory search, hygiene sweep
- Forensic audit fixing 10 issues across 8 files
- Post-close drills and promotion gate

**Day 5 (February 12-13): Legacy Closure**

- v2.9.1-rc1: Legacy test isolation, shims, release notes
- v2.9.1 GA promotion
- v2.9.2 scope document, legacy import closure, flaky test stabilization
- v2.9.2 GA artifacts

**Day 6 (February 13-14): v2.10 Development**

- v2.10 feature commit: Real VLM inference, sentence chunker, MCP boot, policy tests
- v2.10 hardening sweep: Memory engine, model router, scripts, tests

This development velocity was achieved through a combination of clear architectural vision (defined on Day 1), automated promotion gates (preventing regressions), and a disciplined stage-based development model where each stage built on verified foundations.

---

## 27. Current System State Assessment

**Overall Health: OPERATIONAL**

| Aspect | Status | Evidence |
|--------|--------|---------|
| Core Services | 6/6 implemented | All services have real implementations |
| Vision Services | 2/2 implemented | Privacy gate, VLM inference working |
| Integration Tests | ~580+ passing | All green as of v2.9.0 |
| Release Discipline | Strong | 12-16 gate promotions, SHA-256 manifests |
| Documentation | Comprehensive | 18+ doc files, stage-by-stage coverage |
| Security Model | Complete | 4-tier safety, root contract, audit trails |
| Observability | Good | Correlation IDs, JSONL logs, diagnostics |
| Training Pipeline | Functional | Complete fine-tuning and publishing workflow |
| Avatar System | Prototype | High-quality assets, web viewer prototype |

**Maturity Assessment by Component:**

| Component | Maturity | Rationale |
|-----------|----------|-----------|
| API Gateway | Production-ready | Comprehensive routing, error handling, circuit breaker, 37 modules |
| Model Router | Production-ready | Multi-provider, health tracking, fallback matrix, budget guard |
| Memory Engine | Production-ready | Hybrid search, provenance, migrations, WAL-mode SQLite |
| Pipecat | Beta | Full pipeline implemented, limited real-world voice testing |
| OpenClaw | Production-ready | 13 capabilities, safety gate, audit trail, 3 executor types |
| EVA-OS | Beta | Real supervision and health probing, limited orchestration |
| Vision Capture | Alpha | Privacy gate verified, minimal integration testing |
| Perception | Alpha | VLM inference working, limited production exposure |
| MCP Server | Alpha | Basic implementation, new in v2.10 |
| Companion UI | Prototype | Design defined (Zustand FSM), minimal code implementation |
| Training Pipeline | Beta | Working fine-tuning and publishing, one successful training run |
| Avatar System | Prototype | High-quality assets, scripts, web viewer, no live integration |

**Code Metrics:**

| Metric | Value |
|--------|-------|
| Python source files | ~160+ |
| Total source code (services) | ~600KB+ |
| Test files | 57 |
| Test-to-source ratio | ~0.36 |
| Largest file | `action_pipeline.py` (37.2KB) |
| Total integration tests | ~580+ |
| Operational scripts | 100+ |
| Configuration files | 15+ |
| Documentation files | 18+ |
| Git commits | 80 |
| Release tags | 10 |

---

## 28. Technical Debt Inventory

**Critical Debt:**

1. **Stale configuration references**: `sonia-config.json` references `S:\shared\schemas` (moved to `S:\config\schemas`). `app.yaml` references `/health` (should be `/healthz`) and `S:\configs` (should be `S:\config`). These will cause failures if any code parses these paths.

2. **In-memory session state**: Sessions exist only in Gateway memory. A service restart loses all active sessions. This is acceptable for single-operator use but blocks multi-session deployment.

3. **Non-persistent HNSW vector index**: The vector index must be rebuilt on every Memory Engine restart. For large corpora, this rebuild time could become prohibitive.

**Structural Debt:**

4. **`services/tool-service/`**: Legacy tool execution service that predates OpenClaw. Functionality overlaps significantly. Should be deprecated and removed.

5. **Dual configuration format**: Mix of JSON and YAML configs with conflicting values. Should converge on a single format.

6. **Monolithic main.py files**: API Gateway's `main.py` (33.5KB) and Memory Engine's `main.py` (29KB) have grown beyond maintainable size. Should be decomposed into focused modules.

7. **458 empty session files**: `S:\data\sessions\` contains 458 session JSON files (233 bytes each), mostly empty test artifacts. Should be periodically pruned.

8. **`baselines/` directory**: 4 frozen baseline snapshots from February 8. ~50MB of duplicate code from early development. Could be archived.

**Operational Debt:**

9. **No container packaging**: All services run as bare processes. No Docker images, no resource limits, no auto-restart beyond what PowerShell scripts provide.

10. **PowerShell-only operations**: All operational scripts are Windows-only PowerShell. Cross-platform deployment requires porting critical scripts to Python.

11. **No CI/CD automation**: GitHub Actions workflow exists (`sonia-build-gate.yml`) but is not actively used. Promotion gates run manually.

12. **No authentication**: The system assumes a single trusted operator. No user authentication, no session tokens, no API keys.

13. **No TLS**: All inter-service communication is plain HTTP on localhost. Acceptable for single-machine deployment but not for networked environments.

**Code-Level Debt:**

14. **`__pycache__` in git**: Compiled Python files tracked in version control. Should be added to `.gitignore` more aggressively.

15. **Test boilerplate**: Every integration test file duplicates `sys.path.insert(0, r"S:\services\api-gateway")`. Should use a shared conftest.

16. **Completion reports in source**: `PHASE_*_COMPLETION_REPORT.md` files mixed with service source code. Should be moved to `docs/reports/`.

17. **Duplicate FBX files**: Same 11MB FBX model exists in both `assets/avatar/` and `ui/Female Advanced V2 3D Model/`.

---

## 29. What Remains: The Unfinished Work

Based on the published roadmap, the architectural documentation, and the current implementation state, the following work remains to bring SONIA to its envisioned completion.

**Immediate (v2.10 GA):**

1. **MCP Server Integration**: The Claude Code MCP bridge is new in v2.10 and needs hardening -- error handling, reconnection logic, capability exposure, and integration tests.

2. **VLM Inference Robustness**: Real VLM inference works but needs production hardening: GPU memory management, timeout handling for large images, fallback to cloud when local GPU is saturated, and streaming inference support.

3. **Sentence Chunker Validation**: The new sentence-level chunker needs validation against a real document corpus to ensure chunk quality does not degrade for edge cases (tables, code blocks, multi-language text).

4. **Configuration Cleanup**: Fix the three stale path references identified in this report. Unify the JSON/YAML configuration into a single authoritative source.

5. **Session File Pruning**: Add automated pruning of empty session files to the cadence scripts.

**Short-Term (v2.11-2.12):**

6. **Persistent Vector Index**: Save the HNSW index to disk and load on startup. This eliminates the re-indexing delay on Memory Engine restarts and is critical for scaling the memory corpus.

7. **Session Persistence**: Replace in-memory sessions with SQLite or Redis-backed storage. This enables session survival across Gateway restarts and is a prerequisite for multi-session deployment.

8. **User Authentication**: Implement JWT or OAuth2 authentication for multi-user support. The current single-operator model cannot scale to team use.

9. **TLS for Inter-Service Communication**: Add self-signed TLS certificates for localhost communication. While the current setup is single-machine, any future networked deployment requires encrypted transport.

10. **Container Packaging**: Create Docker/Podman images for each service. This enables reproducible deployment, resource limiting, and container orchestration readiness.

11. **CI/CD Activation**: Flesh out the GitHub Actions workflow with at least import checks, type checking, and integration test execution on push.

12. **Voice Production Hardening**: Pipecat needs real-world voice testing beyond the current unit and integration tests. Specific areas include: microphone quality handling, background noise robustness, multi-accent ASR performance, and TTS naturalness evaluation.

**Medium-Term (v2.13-3.0):**

13. **PostgreSQL Migration**: Replace SQLite with PostgreSQL for the Memory Engine. This enables multi-user data isolation, better concurrent access, and horizontal scaling via read replicas.

14. **Message Queue**: Introduce RabbitMQ or Redis Streams for asynchronous inter-service communication. Currently all communication is synchronous HTTP, which creates tight coupling between services.

15. **Kubernetes Deployment**: Create Helm charts and Kubernetes manifests for cloud-native deployment. This enables auto-scaling, rolling updates, and service mesh integration.

16. **Multi-Tenant Isolation**: Implement per-user data partitioning in the Memory Engine and session management. Required for any shared or team deployment.

17. **Plugin System**: Design and implement a plugin architecture for third-party tool/executor extensions to OpenClaw. The current 13 capabilities are hardcoded.

18. **Mobile/Web Client**: Build a React/Next.js companion application that provides the full SONIA experience through a web browser. The current UI is a minimal prototype.

19. **Live Avatar Integration**: Connect the avatar system (Blender/Unity rendering + LiveAvatar model) to the real-time voice pipeline for synchronized lip sync, gestures, and facial expressions during conversation.

20. **Prometheus/Grafana Stack**: Implement the metrics and dashboarding system planned in the architecture document. Each service should expose Prometheus-compatible `/metrics` endpoints.

**Long-Term Vision (v3.0+):**

21. **Distributed Deployment**: Support running SONIA services across multiple machines with shared state, service discovery, and load balancing.

22. **High Availability**: Implement service replication, failover, and the 99.9% uptime target specified in the roadmap.

23. **Enterprise Features**: SOC2/HIPAA compliance, RBAC/ABAC permission model, operator team collaboration, delegation workflows, and compliance reporting.

24. **Advanced Memory**: Knowledge graph construction from ingested documents, multi-modal memory (images, audio, documents), and cross-session learning.

25. **OpenTelemetry Integration**: Replace the current correlation-ID-based tracing with full OpenTelemetry distributed tracing for production-grade observability.

---

## 30. Strategic Outlook and Future Architecture

SONIA stands at an inflection point. The foundational architecture -- microservices, safety model, memory system, voice pipeline, desktop automation, supervision -- is complete and proven through 580+ integration tests and multiple release cycles. The system works. The question now is what "working" should look like at production scale.

**Architecture Maturity:**

The current architecture is exceptionally well-suited for its target deployment: a single operator on a single Windows machine with a high-end GPU. Every design decision -- SQLite over PostgreSQL, in-memory sessions, bare-process management, PowerShell operations -- optimizes for this scenario. The system starts in seconds, requires no external infrastructure, and provides full-stack AI agent capabilities locally.

However, this same set of decisions creates barriers to scaling beyond the single-operator model. PostgreSQL would enable multi-user storage. Redis would enable distributed sessions. Container orchestration would enable multi-machine deployment. Each of these transitions is individually straightforward but collectively represents a significant architectural evolution.

**The Scaling Strategy:**

The recommended scaling strategy is to evolve SONIA through three phases:

*Phase 1 (Current -> v2.12)*: Harden the existing single-machine deployment. Fix configuration debt, persist the vector index, add session persistence, and implement authentication. The goal is production-grade reliability for a single operator.

*Phase 2 (v2.13 -> v2.15)*: Add infrastructure for team deployment. PostgreSQL for shared storage, Redis for distributed sessions, Docker containers for deployment, and basic CI/CD. The goal is supporting 2-5 concurrent operators on a single machine or small cluster.

*Phase 3 (v3.0+)*: Full distributed deployment with Kubernetes, service mesh, horizontal scaling, and enterprise features. The goal is supporting 100+ concurrent users with high availability guarantees.

**The Competitive Position:**

SONIA's architectural advantages are:

1. **Deterministic Safety**: The 4-tier risk model with cryptographic approval tokens is more rigorous than any competing AI agent platform.

2. **Hybrid Memory**: The combination of BM25, vector search, and provenance tracking provides richer context recall than pure vector-search approaches.

3. **Voice-First Design**: The Pipecat integration with sub-200ms latency targets makes SONIA genuinely voice-native rather than voice-bolted-on.

4. **Local-First Philosophy**: Running entirely on local hardware eliminates cloud dependency, reduces latency, and preserves data privacy.

5. **Desktop Autonomy**: The 13-capability action system with safety gates enables genuine desktop automation that no cloud-only assistant can provide.

**The Risk Assessment:**

1. **Single-developer velocity**: The six-day build demonstrates exceptional velocity but also creates key-person risk. The codebase needs documentation density sufficient for onboarding additional developers.

2. **GPU dependency**: The ML stack requires significant GPU resources (~24GB VRAM minimum). GPU availability and pricing directly impact deployment feasibility.

3. **Dependency freshness**: The frozen requirements include rapidly-evolving packages (PyTorch, Unsloth, websockets) that may require updates for security or compatibility. The dependency-lock system mitigates version drift but not CVE exposure.

4. **Test coverage breadth vs. depth**: 580+ integration tests provide excellent breadth across features, but individual module unit test coverage is thinner. A subtle logic bug in a well-integrated module might pass all integration tests while still causing incorrect behavior.

**Conclusion:**

SONIA is a technically ambitious project that has achieved remarkable completeness in a short timeframe. The architectural foundations are sound, the safety model is rigorous, and the test infrastructure is comprehensive. The primary challenges ahead are operational hardening (configuration cleanup, session persistence, vector index persistence), production readiness (authentication, TLS, containers), and scaling (PostgreSQL, Redis, Kubernetes).

The most impactful near-term work is completing v2.10 GA (MCP integration, VLM hardening, config cleanup), followed by session and vector persistence (v2.11), and authentication (v2.12). Each of these milestones makes the system incrementally more production-ready without requiring architectural changes.

The long-term vision of a deterministic, voice-first, locally-deployed AI agent with full desktop autonomy and enterprise-grade safety governance is within reach. The architecture supports it. The code implements it. What remains is the engineering discipline to harden, scale, and polish what has been built.

---

## Appendix A: Complete Port Map

| Port | Service | Status | Health Endpoint |
|------|---------|--------|-----------------|
| 7000 | API Gateway | Active | `/healthz` |
| 7010 | Model Router | Active | `/healthz` |
| 7020 | Memory Engine | Active | `/healthz` |
| 7030 | Pipecat | Active | `/healthz` |
| 7040 | OpenClaw | Active | `/healthz` |
| 7050 | EVA-OS | Active | `/healthz` |
| 7060 | Vision Capture | Optional | `/healthz` |
| 7070 | Perception | Optional | `/healthz` |
| 8000 | Orchestrator | Separate | N/A |
| 11434 | Ollama | External | `/api/tags` |

## Appendix B: Complete Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11 |
| Web Framework | FastAPI | 0.116.1 |
| ASGI Server | Uvicorn | 0.35.0 |
| Validation | Pydantic | 2.11.7 |
| HTTP Client | httpx | 0.28.1 |
| WebSocket | websockets | 16.0 |
| Database | SQLite 3 | WAL mode |
| ML Framework | PyTorch | 2.10.0+cu128 |
| ML Training | Unsloth | 2026.1.4 |
| Training Tools | TRL, PEFT, accelerate | 0.24.0, 0.18.1, 1.12.0 |
| Quantization | bitsandbytes | 0.49.1 |
| Tokenizers | tokenizers, sentencepiece | 0.22.2, 0.2.1 |
| ASR | faster-whisper (CTranslate2) | Large-v3 |
| VLM | Qwen3-VL-32B-Instruct | Custom fine-tune |
| Embeddings | Qwen3-Embedding-8B | GGUF f16 |
| Reranker | Qwen3-Reranker-8B | GGUF f16 |
| TTS | Qwen3-TTS-Tokenizer | 12Hz |
| LLM Inference | Ollama | Local |
| Cloud LLM | Anthropic, OpenRouter | httpx |
| 3D Rendering | Blender | Python scripts |
| Game Engine | Unity | C# scripts |
| UI Framework | React, Three.js | TypeScript |
| Build Tool | Vite | Web UI |
| Operating System | Windows 11 Pro | Primary target |
| Shell | PowerShell 5.1 | Operations |
| Version Control | Git | GitHub (private) |
| Package Manager | pip (frozen), conda (env) | conda prefix |

## Appendix C: Git Tag Timeline

| Tag | Commit | Date | Description |
|-----|--------|------|-------------|
| `RC1-20260208` | `df0e107` | Feb 8 | Initial baseline after repair |
| `RC1.1-20260208` | `72073ea` | Feb 8 | .gitignore expansion |
| `RC1.2-20260208` | `2a7e673` | Feb 8 | Action safety layer merge |
| `v2.4.0-stage4` | `c5a8de7` | Feb 8 | Multimodal sessions release |
| `v2.5.0-stage5` | `515c81c` | Feb 8 | Action pipeline + desktop adapters |
| `v2.5.0-rc1` / `v2.5.0` | `a6f33da` | Feb 8-9 | Reliability hardening GA |
| `v2.6.0` | `f887f8f` | Feb 9 | Companion experience layer |
| `v2.7.0` | `c0c4135` | Feb 10 | Companion runtime integration |
| `v2.8.0-rc1` | `552c1b7` | Feb 10 | Deterministic operations RC |
| `v2.8.0` | `f1612f8` | Feb 10 | Deterministic operations GA |
| `v2.9.0` | `50b1038` | Feb 11 | System closure |
| `v2.9.1-rc1` | `0e16b6e` | Feb 12 | Legacy test isolation |
| `v2.9.1` | `fbdec98` | Feb 12 | Legacy test isolation GA |
| `v2.9.2` | `dc6c7b3` | Feb 13 | Legacy closure |

## Appendix D: File Count by Directory

| Directory | Python Files | Other Files | Total |
|-----------|-------------|-------------|-------|
| services/api-gateway/ | 37 | 2 | 39 |
| services/model-router/ | 8 | 1 | 9 |
| services/memory-engine/ | 18 | 7 | 25 |
| services/pipecat/ | 18 | 1 | 19 |
| services/openclaw/ | 18 | 3 | 21 |
| services/eva-os/ | 7 | 1 | 8 |
| services/vision-capture/ | 1 | 0 | 1 |
| services/perception/ | 2 | 0 | 2 |
| services/shared/ | 3 | 0 | 3 |
| services/orchestrator/ | 2 | 2 | 4 |
| services/mcp-server/ | 2 | 1 | 3 |
| services/tool-service/ | 4 | 0 | 4 |
| tests/ | 57 | 1 | 58 |
| scripts/ | 15 | 100+ | 115+ |
| pipeline/ | 4 | 1 | 5 |
| training/ | 10 | 5 | 15 |
| config/ | 0 | 15 | 15 |
| docs/ | 0 | 25+ | 25+ |
| **Total** | **~200** | **~170** | **~370+** |

---

**End of Report**

*SONIA Deep-Dive Report v1.0 -- Generated February 14, 2026*
*Total: 30 sections + 4 appendices*
*Covers: Architecture, implementation, testing, deployment, training, avatar, release engineering, chronology, technical debt, future work*
