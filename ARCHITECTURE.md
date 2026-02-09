# Sonia Architecture

## System Overview

Sonia is a deterministic, voice-first agent platform with mission-critical policy enforcement through EVA-OS supervisor. The architecture emphasizes safety, observability, and composability.

### Core Principles

1. **Deterministic Control**: EVA-OS makes all policy decisions; models propose, supervisor decides
2. **Composability**: Service-swappable via canonical message contracts
3. **Observable**: Full causality tracking (correlation IDs, trace IDs)
4. **Safe by Default**: Risk-tiered approval workflow, root contract enforcement
5. **Local-First**: All core services run locally; cloud integration optional

## Microservice Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Client (UI / Voice)                    │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   API Gateway (Port 7000)     │
         │  - Input normalization        │
         │  - Session management         │
         │  - Rate limiting              │
         │  - WebSocket upgrade          │
         └────┬──────┬──────┬───────┬────┘
              │      │      │       │
    ┌─────────▼─┐  ┌─▼──────▼─┐ ┌──▼──────┐ ┌─────────────┐
    │ Model     │  │  Memory  │ │Pipecat  │ │   OpenClaw  │
    │ Router    │  │  Engine  │ │(Voice)  │ │(Execution)  │
    │(7010)     │  │(7020)    │ │(7030)   │ │(7040)       │
    └─────┬─────┘  └──┬──────┬┘ └────┬────┘ └──┬──────┬────┘
          │           │      │       │         │      │
          │      ┌────▼──────▼┐      │    ┌────▼──────▼─┐
          │      │ Vector DB  │      │    │ Desktop /   │
          │      │ + SQLite   │      │    │ Browser     │
          │      └────────────┘      │    └─────────────┘
          │                          │
          └───────────┬──────────────┘
                      │
          ┌───────────▼──────────┐
          │   EVA-OS Supervisor  │
          │  - Policy decisions  │
          │  - Risk gating       │
          │  - Approval tokens   │
          │  - Root contract     │
          └──────────────────────┘
```

### Service Responsibilities

#### API Gateway (7000)
- **Role**: Stable front door for all clients
- **Responsibilities**:
  - Input validation and normalization
  - Session/authentication management
  - Rate limiting and DoS protection
  - Request ID generation (correlation)
  - Proxying to downstream services
  - WebSocket upgrade for voice
  - Response transformation and error handling

#### Model Router (7010)
- **Role**: Intelligent model selection and routing
- **Responsibilities**:
  - LLM provider management (Ollama, OpenRouter, Anthropic, LMStudio, vLLM)
  - Adaptive routing based on latency/cost
  - Prompt engineering and context window management
  - Embeddings generation
  - Response caching
  - Token counting and cost tracking

#### Memory Engine (7020)
- **Role**: Persistent, searchable memory with provenance
- **Responsibilities**:
  - Event ledger storage (durable, append-only)
  - Bi-temporal (valid + transaction time) storage
  - Document ingestion and chunking
  - Vector embeddings and semantic search
  - Full-text search (BM25)
  - Snapshot generation for context optimization
  - Forgetting/decay strategies

#### Pipecat (7030)
- **Role**: Real-time voice and modality gateway
- **Responsibilities**:
  - WebSocket streaming (audio, text, events)
  - Voice Activity Detection (VAD)
  - Automatic Speech Recognition (ASR)
  - Text-to-Speech (TTS)
  - Turn-taking and interruption handling
  - Latency optimization (<200ms target)
  - Audio quality metrics and monitoring

#### OpenClaw (7040)
- **Role**: Deterministic action execution with governance
- **Responsibilities**:
  - Desktop automation (mouse, keyboard, screenshot)
  - Browser control and UI automation
  - Filesystem operations (with root contract enforcement)
  - Terminal/shell command execution
  - Action result verification
  - Audit logging of all executed actions
  - Risk-tiered approval gating

#### EVA-OS (Future 7050)
- **Role**: Policy decision making and safety
- **Responsibilities**:
  - Tool call risk classification
  - Approval token generation and validation
  - Operational mode management
  - Service health aggregation
  - Root contract enforcement
  - Policy violation detection

## Message Contract System

All inter-service communication uses canonical JSON envelopes:

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "service_from": "api-gateway",
  "service_to": "model-router",
  "message_type": "chat_request",
  "timestamp": "2026-02-08T14:30:00.000Z",
  "body": {
    "user_input": "What is the weather?",
    "context": [...],
    "model": "claude-3-5-sonnet"
  },
  "metadata": {
    "correlation_id": "550e8400-e29b-41d4-a716-446655440001",
    "trace_id": "550e8400-e29b-41d4-a716-446655440002",
    "parent_id": null,
    "user_id": "user-123",
    "session_id": "session-456"
  },
  "signature": "base64_hmac_sha256"
}
```

**Benefits**:
- Service-agnostic communication
- Complete causality tracking
- Signature verification
- Enables service swapping (e.g., replace Pipecat with WebRTC)
- Composability: downstream doesn't care about upstream implementation

## Data Flow

### Chat Flow
```
1. Client sends message to API Gateway
2. API Gateway validates, creates session, normalizes input
3. API Gateway → Model Router: chat_request
4. Model Router queries memory for context
   - Memory Engine: memory_query
5. Model Router → LLM Provider (Ollama/Anthropic/etc.)
6. Model Router → EVA-OS: tool_calls_to_gate
7. EVA-OS: risk classification, approval token generation
8. EVA-OS → API Gateway: approval_required or tool_approved
9. If approval required: API Gateway → Client: approval_prompt
10. Client/Operator approves or denies
11. If approved: OpenClaw executes action
12. OpenClaw → Memory Engine: memory_append (action result)
13. Model Router receives execution result
14. Model Router → Memory Engine: memory_append (completed turn)
15. API Gateway → Client: response_complete
```

### Voice Flow
```
1. Client opens WebSocket to API Gateway /stream/{session_id}
2. API Gateway upgrades to WebSocket, creates Pipecat session
3. Client sends audio chunks
4. API Gateway → Pipecat: audio_frames
5. Pipecat: VAD detection, ASR transcription (partial)
6. Pipecat → API Gateway: partial_transcript
7. API Gateway → Client: transcript (server-sent events)
8. When silence detected: Pipecat considers turn complete
9. Pipecat → Model Router: chat_request (with transcript)
10. Model Router processes (same as chat flow above)
11. Model Router → Pipecat: response (streaming)
12. Pipecat: TTS generation, streaming audio back
13. Pipecat → Client: audio frames
14. Client plays audio
15. If client interrupts: Client sends interrupt_signal
16. Pipecat: Cancels TTS output, returns to listening
17. Cycle continues
```

## Storage Architecture

### Filesystem Layout
```
S:\ (Canonical Root)
├── config/               # Configuration files
│   └── sonia-config.json
├── shared/              # Shared libraries
│   ├── schemas/
│   └── utils/
├── backend/             # Backend services
│   └── services/
│       ├── api-gateway/
│       ├── model-router/
│       ├── memory-engine/
│       ├── pipecat/
│       └── openclaw/
├── ui/                  # Desktop UI
│   └── desktop/
├── logs/                # Service logs
│   ├── services/        # stdout/stderr per service
│   └── audit/           # Audit trail
├── state/               # Runtime state
│   ├── pids/            # Process IDs
│   ├── sessions/        # Active sessions
│   └── locks/           # Distributed locks
├── data/                # Persistent data
│   ├── memory/          # Memory ledger (SQLite + JSON)
│   ├── vector/          # Vector embeddings (HNSW index)
│   └── uploads/         # User uploaded files
└── artifacts/           # Build artifacts
```

### Memory Engine Storage

#### Ledger (Append-Only)
```
SQLite Database: S:\data\memory\ledger.db
┌─────────────────────────────────┐
│ events (append-only log)        │
├─────────────────────────────────┤
│ id (PK)                         │
│ event_type (UserTurn, ...)      │
│ timestamp (ISO-8601)            │
│ correlation_id                  │
│ entity_id (session, user, ...)  │
│ payload (JSON)                  │
│ signature (HMAC-SHA256)         │
└─────────────────────────────────┘
```

#### Vector Store
```
HNSW Index: S:\data\vector\sonia.hnsw
- Dense vectors for all chunks
- Cosine similarity search
- ~1536 dimensions (depends on embedding model)
- Approximate nearest neighbor search
```

#### Snapshots
```
S:\data\memory\snapshots/
├── 2026-02-08T14-00-00Z_session-123.json
├── 2026-02-08T15-00-00Z_session-456.json
└── ...
```

## Deployment Models

### Local Development
```
All services running on localhost:7000-7040
Configuration: S:\config\sonia-config.json
Development mode: DEBUG=1, no SSL, in-memory caches
```

### Single-Machine Production
```
All services on same machine
Configuration: environment-specific (prod vs staging)
SSL/TLS for all inter-service communication
Systemd/Windows Services for process management
Centralized logging to journald/Event Log
Backup: S:\data\memory\backups\ (24h snapshots)
```

### Distributed (Future: v2.0)
```
Load balancer → Multiple API Gateway replicas
Shared cache (Redis)
Distributed memory ledger (PostgreSQL)
Vector DB cluster (Milvus/Weaviate)
Message queue (RabbitMQ/Kafka) for async events
Service mesh (Istio) for reliability
```

## Security Architecture

### Trust Boundaries
```
┌─────────────────────────────────────────────┐
│         Untrusted: Client Input             │
└────────────────────┬────────────────────────┘
                     │ Validated
                     ▼
┌─────────────────────────────────────────────┐
│      Trusted: API Gateway & EVA-OS          │
└────────────────────┬────────────────────────┘
                     │ Policy checked
                     ▼
┌─────────────────────────────────────────────┐
│  Trusted: Model Router, Memory, Pipecat     │
└────────────────────┬────────────────────────┘
                     │ Approval token checked
                     ▼
┌─────────────────────────────────────────────┐
│      Trusted: OpenClaw (Execute)            │
└─────────────────────────────────────────────┘
```

### Risk-Tiered Approval
```
TIER_0 (Read-Only): Auto-execute
  - filesystem.list, filesystem.read, filesystem.stat
  - process.list, http.get

TIER_1 (Create): 30s auto-gate
  - filesystem.create_dir, process.start_approved

TIER_2 (Modify): Explicit approval (5min timeout)
  - filesystem.write, filesystem.move, process.stop

TIER_3 (Destroy): Explicit approval + confirmation code
  - filesystem.delete, process.kill, shell.arbitrary_command
```

## Observability

### Logging Strategy
- **Application logs**: S:\logs\services\<service>.out.log
- **Error logs**: S:\logs\services\<service>.err.log
- **Audit trail**: S:\logs\audit\
- **Format**: JSON with correlation IDs
- **Retention**: 90 days (configurable)

### Metrics
- Prometheus-compatible /metrics endpoint on each service
- Request counts, latencies, errors
- Service-specific metrics (memory items, vector searches, voice sessions, etc.)
- Scrape interval: 15 seconds
- 15-day retention

### Tracing
- OpenTelemetry-compatible (future)
- Correlation IDs propagated across all services
- Trace context in all logs
- Distributed tracing backend (Jaeger/Zipkin)

---

**Architecture Version**: 1.0
**Effective Date**: 2026-02-08
**Last Updated**: 2026-02-08
