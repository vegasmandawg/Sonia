# Sonia Runtime Contract

## Overview

The Sonia Runtime Contract defines the operational guarantees, service level agreements (SLAs), and system boundaries that operators and integrators must understand when deploying Sonia.

## Canonical Boundaries

### Filesystem Root
```
Canonical Root: S:\
Non-negotiable: ALL operations scoped to S:\ or subdirectories
Violation: EVA-OS rejects any filesystem operation outside S:\
Exception: None (hard boundary enforced)
```

### Port Assignment (Hard-Coded)
```
7000  → API Gateway (stable front door)
7010  → Model Router (provider selection)
7020  → Memory Engine (persistence, retrieval)
7030  → Pipecat (real-time voice/modality)
7040  → OpenClaw (action execution)
7050  → EVA-OS (policy decisions) [planned]
```

Conflict: If ports unavailable, services fail to start. No dynamic port assignment.

### Service Health Contract
```
Every service MUST expose:
  GET /health           → 200 OK {status: "healthy"}
  GET /status           → 200 OK {service_info...}
  
Health check interval: 30 seconds (configurable)
Timeout: 5 seconds per health check
Max consecutive failures: 3 (then service marked unhealthy)
Degraded threshold: Any health check >2 seconds latency
```

## Message Contract Guarantees

### Envelope Structure
Every service-to-service message MUST conform to canonical envelope:
```json
{
  "message_id": "uuid-v4",
  "service_from": "service-name",
  "service_to": "service-name",
  "message_type": "UserTurn|SystemEvent|Plan|ToolCall|...",
  "timestamp": "ISO-8601",
  "body": {...},
  "metadata": {
    "correlation_id": "uuid-v4",
    "trace_id": "uuid-v4",
    "parent_id": "uuid-v4"
  },
  "signature": "base64-encoded-hmac"
}
```

### Validation Rules
- All service-to-service traffic MUST be valid JSON
- All required fields MUST be present
- HMAC signature MUST verify (key: config.secrets.sonia_key)
- Correlation IDs MUST propagate across all services
- Trace IDs used for distributed tracing

## Latency Guarantees

### Service Response Times (p99)

| Service | Endpoint | Guarantee |
|---------|----------|-----------|
| API Gateway | /chat | <1000ms |
| Model Router | /models/chat | <5000ms* |
| Memory Engine | /search | <500ms |
| Pipecat | /stream | <200ms |
| OpenClaw | /actions/execute | <2000ms |

*Model Router latency depends on upstream LLM provider (Ollama, OpenRouter, Anthropic, etc.). Sonia adds <500ms overhead.

### SLA Formula
```
SLA = (Successful Requests / Total Requests) × 100%
Minimum acceptable: 99% uptime
Degraded threshold: 95-99% (warning)
Critical threshold: <95% (alert)
```

## Tool Execution Guarantees

### Risk Tiers and Approval Requirements

**TIER_0 (Read-Only)**: Automatic execution
- filesystem.list, filesystem.read, filesystem.stat
- process.list
- http.get

**TIER_1 (Low-Risk Modifications)**: Approval gate (30s timeout)
- filesystem.create (directories), process.start (approved processes)
- http.head

**TIER_2 (Medium-Risk)**: Explicit approval + operator confirmation
- filesystem.write, filesystem.append
- filesystem.move, filesystem.copy
- process.stop

**TIER_3 (Destructive)**: Explicit approval + operator confirmation + confirmation code
- filesystem.delete
- process.kill
- shell.arbitrary_command

### Approval Token Format
```
scope_hash = HMAC-SHA256(tool_name + "|" + args_json, key)
token = {
  "scope_hash": scope_hash,
  "expires_at": now + 5min,
  "operator_id": operator_uuid,
  "approval_code": random_6_digit
}
```

Tokens are **single-use and scope-bound** (cannot be reused for different actions).

## Memory Guarantees

### Durability
- All memory writes persisted to S:\data\memory\
- SQLite transaction log for ACID compliance
- Write-ahead logging (WAL) mode enabled
- Backup snapshot every 24 hours to S:\data\memory\backups\

### Consistency
- Bi-temporal storage: valid_time + transaction_time
- Causality preserved across all events
- Conflict resolution: Last-write-wins for same (entity_id, valid_time)
- Versioning: Full history retained

### Retrieval SLA
- Search <500ms for corpus <1M items
- Ranking: BM25 + semantic (TBD v1.1)
- Results: Top-k ordered by relevance + recency

## Voice and Streaming

### WebSocket Protocol Contract (Pipecat)
```
Connection:
  URL: ws://127.0.0.1:7030/stream/{session_id}
  Auth: Bearer token (from API Gateway session)
  Reconnect: Automatic with exponential backoff (max 5 retries)

Message Format:
  {
    "type": "audio|text|event",
    "sequence": integer,
    "timestamp": ISO-8601,
    "payload": {...}
  }

Voice Streaming:
  Sample rate: 16kHz mono
  Encoding: PCM 16-bit or mulaw
  Chunk size: 160-480 samples per message
  Latency target: <200ms round-trip
```

### Barge-In Handling
- Client can interrupt server at any time
- Server cancels current TTS output within 100ms
- New ASR context begins immediately

## Failure Modes and Recovery

### Service Failure
```
If service fails:
  1. Health check detects failure (within 30s)
  2. Auto-restart initiated (if RestartPolicy=Always)
  3. Dependent services degraded but operational
  4. Operator notified (if AlertingEnabled)
  5. Client requests routed to fallback (if configured)

Max downtime per incident: 5-10 seconds
Recovery time: <30 seconds typical
```

### Data Corruption Detection
```
Ledger validation runs every 1 hour:
  - Check all event signatures
  - Verify transaction log integrity
  - Detect orphaned entries
  
If corruption detected:
  - Alert raised immediately
  - Rollback to last verified snapshot
  - Manual investigation required
```

### Network Partition (Distributed Systems Only)
```
If service cannot reach another service:
  1. Retry logic: exponential backoff, max 30s total
  2. Circuit breaker opens after 3 consecutive failures
  3. Fallback responses returned to clients
  4. Partition healed automatically when connectivity restored
  5. Replay queue processed on reconnection
```

## Configuration Validation

### Startup Checks
Every service performs these checks before serving requests:

1. **Root Contract**: Verify S:\ exists and is writable
2. **Configuration**: Load and validate sonia-config.json
3. **Dependencies**: Check all external service endpoints
4. **Storage**: Verify S:\data\, S:\logs\, S:\state\ directories
5. **Ports**: Confirm assigned ports are available
6. **Secrets**: Load and validate all required secrets

Failure in any check → service refuses to start (fail-fast principle).

## Monitoring and Observability

### Required Metrics (Prometheus-compatible)

```
sonia_service_requests_total{service=, endpoint=, status=}
sonia_service_request_duration_seconds{service=, endpoint=, quantile=}
sonia_service_errors_total{service=, error_type=}
sonia_memory_items_total{service=memory-engine}
sonia_tool_executions_total{tier=, status=}
sonia_approval_requests_pending{status=}
sonia_vector_search_latency_seconds{quantile=}
```

### Logging Standards
All services log to S:\logs\services\<service>.out.log and .err.log

Log levels:
- ERROR: Service failures, data corruption, security violations
- WARN: Degraded performance, retry exhaustion, deprecated APIs
- INFO: Service startup/shutdown, successful operations, config loaded
- DEBUG: Detailed request/response traces (only when DEBUG=1)

## Upgrade and Compatibility

### Version Contract
```
Format: MAJOR.MINOR.PATCH
- MAJOR: Breaking changes to service APIs or message contracts
- MINOR: New features (backwards compatible)
- PATCH: Bug fixes (backwards compatible)

Supported versions: Current + Previous MINOR (e.g., 1.2.x and 1.1.x)
Deprecated versions: >2 MINOR versions behind
```

### Breaking Change Policy
- Announce 1 version in advance (DEPRECATION warning in logs)
- Provide migration guide
- Support dual-format requests (old + new) during transition
- Drop old format only in MAJOR version bump

## Security Boundaries

### Trust Model
```
Trusted:
  - EVA-OS policy decisions (deterministic, auditable)
  - Operator approvals (authenticated, logged)
  - System configuration (signed by admin)

Untrusted:
  - Client input (validated, sanitized)
  - LLM model outputs (constrained, bounded)
  - External service responses (timeouts, circuit breakers)
```

### Secrets Management
```
Never in:
  - Configuration files (except sonia-config.json, which is not committed)
  - Environment variables (except specific SONIA_* variables)
  - Logs or audit trails
  - Error messages returned to clients

Stored in:
  - S:\secrets\ (encrypted at rest)
  - Environment variables only at runtime
  - Secrets management system (future: HashiCorp Vault)
```

## Compliance and Audit

### Audit Trail
Every meaningful action logged to S:\logs\audit\:
- Tool execution (what, when, who, result)
- Policy decisions (approval granted/denied, reasoning)
- Configuration changes (before, after, by whom)
- Access to sensitive data (memory, files, API calls)

Retention: 90 days minimum (configurable)

### Compliance Modes
```
HIPAA mode: Additional PII redaction, extended audit retention
GDPR mode: Right-to-be-forgotten support, data minimization
SOC2 mode: Enhanced monitoring, immutable audit logs
```

## Deprecation Timeline

### v1.1 (Q1 2026)
- Memory Engine v1 endpoints unchanged
- New optional v2 endpoints for advanced retrieval

### v1.5 (Q1 2027)
- v1 endpoints marked DEPRECATED
- Warning logged for each use
- Migration guide published

### v2.0 (Q2 2027)
- v1 endpoints removed
- Breaking change in CHANGELOG, ROADMAP updated

---

**Contract Version**: 1.0
**Effective Date**: 2026-02-08
**Next Review**: 2026-05-08
