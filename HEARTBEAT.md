# Sonia Heartbeat Monitor

Health and status monitoring specification for Sonia system components.

## Overview

The Heartbeat system provides continuous monitoring of:
1. Individual service health (alive, responsive, degraded)
2. Inter-service communication (latency, error rates)
3. Resource utilization (CPU, memory, disk, GPU)
4. Data pipeline health (memory ledger, vector store, cache)
5. External dependencies (LLM providers, vector DB, cache)

## Service Health Checks

### Health Endpoint Contract
```
GET /health
Response (200 OK):
{
  "status": "healthy|degraded|unhealthy",
  "service": "service-name",
  "version": "1.0.0",
  "timestamp": "2026-02-08T14:30:00Z",
  "checks": {
    "connectivity": {"status": "pass", "message": "..."},
    "storage": {"status": "pass", "message": "..."},
    "dependencies": {"status": "pass", "details": {...}}
  },
  "uptime_seconds": 86400,
  "memory_mb": 256,
  "cpu_percent": 15.2
}
```

### Polling Interval
- API Gateway: Every 10 seconds (mission-critical)
- Model Router: Every 30 seconds
- Memory Engine: Every 30 seconds
- Pipecat: Every 15 seconds (voice-critical)
- OpenClaw: Every 30 seconds

### Health States

**Healthy**: 
- Service responds to /health within 2s
- All checks return "pass"
- Error rate <1% over 5min window

**Degraded**:
- Service responds within 5s
- Some checks warn/fail (but service operational)
- Error rate 1-5% over 5min window
- Latency 2-5 seconds

**Unhealthy**:
- Service doesn't respond or responds after 5s timeout
- Critical checks failed
- Error rate >5% over 5min window
- Latency >5 seconds

### Status Endpoint Contract
```
GET /status
Response (200 OK):
{
  "service": "api-gateway",
  "version": "1.0.0",
  "timestamp": "2026-02-08T14:30:00Z",
  "operational_mode": "normal|degraded|restricted",
  "requests_processed": 1523456,
  "requests_errored": 234,
  "p99_latency_ms": 1250,
  "downstream_services": {
    "model-router": {"status": "healthy", "latency_ms": 450},
    "memory-engine": {"status": "healthy", "latency_ms": 220},
    "pipecat": {"status": "healthy", "latency_ms": 180},
    "openclaw": {"status": "healthy", "latency_ms": 520}
  }
}
```

## Metrics Collection

### Required Metrics (Prometheus Format)

#### Request Metrics
```
sonia_requests_total{service=, method=, endpoint=, status=}
sonia_request_duration_seconds{service=, endpoint=, quantile=}
sonia_request_errors_total{service=, error_type=}
```

#### Service Metrics
```
sonia_service_health{service=} → 1=healthy, 0.5=degraded, 0=unhealthy
sonia_service_uptime_seconds{service=}
sonia_service_version{service=, version=}
sonia_upstream_dependencies{service=, dependency=, status=}
```

#### Memory Engine Metrics
```
sonia_memory_ledger_items{service=memory-engine}
sonia_memory_search_latency_seconds{quantile=}
sonia_memory_write_latency_seconds{quantile=}
sonia_vector_index_size_bytes{service=memory-engine}
sonia_memory_snapshots_total{service=memory-engine}
```

#### Tool Execution Metrics
```
sonia_tool_calls_total{tier=, status=}
sonia_tool_approval_requests{tier=, status=}
sonia_tool_execution_time_seconds{tool=, quantile=}
```

#### Voice/Pipecat Metrics
```
sonia_voice_sessions_active{service=pipecat}
sonia_voice_latency_ms{quantile=}
sonia_tts_latency_ms{quantile=}
sonia_asr_latency_ms{quantile=}
sonia_turn_taking_interruptions_total{service=pipecat}
```

#### Cache Metrics
```
sonia_cache_hits_total{cache_type=}
sonia_cache_misses_total{cache_type=}
sonia_cache_size_bytes{cache_type=}
sonia_cache_evictions_total{cache_type=}
```

### Metric Collection Method
- Prometheus scrape interval: 15 seconds
- Metrics endpoint: `/metrics` (all services)
- Retention: 15 days (configurable)
- Aggregation: 5min, 1h, 1d windows

## Alert Thresholds

### Critical Alerts (Page Oncall)
```
- Service unavailable (status != healthy) for >2min
- Error rate >10% for >5min
- p99 latency >10s for >5min
- Memory ledger corruption detected
- Disk usage >90%
- Vector store unavailable
```

### Warning Alerts (Ticket Created)
```
- Error rate 5-10% for >5min
- p99 latency 5-10s for >5min
- Service degraded for >5min
- Memory ledger slow queries (>1s)
- Cache hit rate <60%
- Disk usage 80-90%
```

### Info Alerts (Logged, No Notification)
```
- Service restart (automatic recovery)
- Graceful shutdown
- Configuration reload
- Scheduled maintenance starting/ending
```

## Dependency Health

### External Dependency Checks

**LLM Providers** (every 60s):
- Connectivity: Can reach endpoint
- Latency: Response time <5s
- Availability: Error rate <1%
- Fallback: If unavailable, route to backup provider

**Vector Store** (every 30s):
- Connectivity: Can reach endpoint
- Query latency: <200ms for test query
- Index health: Can verify index exists
- Fallback: Use local HNSW if remote unavailable

**Cache System** (every 30s):
- Connectivity: Can reach endpoint
- Get/Set latency: <50ms
- Hit rate tracking
- Fallback: Skip cache if unavailable

**Message Bus** (if used in future):
- Connectivity: Can connect to broker
- Publish latency: <100ms
- Consumer lag: <1s
- Fallback: Use in-memory buffer

## Operational Dashboards

### Main Dashboard
- Service health grid (5 services, real-time status)
- Request rate and error rate (time series)
- Latency percentiles (p50, p95, p99)
- Downstream dependency status
- Alert status and recent incidents

### Memory Engine Dashboard
- Ledger size (items count, storage bytes)
- Search latency distribution
- Write latency distribution
- Vector index stats
- Snapshot status

### Voice Dashboard (Pipecat)
- Active sessions
- Session duration distribution
- Voice latency (VAD, ASR, TTS)
- Interruption rate
- Audio quality metrics

### Tool Execution Dashboard
- Tool calls by type (TIER_0-3)
- Approval request status
- Execution success rate
- Error distribution
- Audit trail recent actions

## Health Check Script

Location: `S:\scripts\healthcheck.ps1`

Usage:
```powershell
# Quick health check
.\scripts\healthcheck.ps1

# Verbose with dependency checks
.\scripts\healthcheck.ps1 -Verbose

# Export metrics to Prometheus format
.\scripts\healthcheck.ps1 -ExportMetrics

# Continuous monitoring (every 10s)
.\scripts\healthcheck.ps1 -Monitor -Interval 10
```

Output:
```
SONIA SYSTEM HEALTH CHECK
=========================

API Gateway (7000)................✓ Healthy
Model Router (7010)...............✓ Healthy
Memory Engine (7020)..............✓ Healthy (P99: 234ms)
Pipecat (7030)...................✓ Healthy (Active: 2 sessions)
OpenClaw (7040)..................✓ Healthy

Upstream Dependencies
=====================
Ollama (local)...................✓ Available
Vector Store.....................✓ Available
Model Cache......................✓ Working (Hit: 78%)

System Resource Status
======================
CPU Usage: 24%
Memory: 2.1 GB / 16 GB (13%)
Disk: 450 GB / 1 TB (45%)
GPU: CUDA available, 8 GB available

All checks passed! ✓
```

## Automated Recovery

### Service Recovery Logic
```
If service unhealthy:
  1. Attempt restart (max 3 times with exponential backoff)
  2. If restart succeeds: resume normal operations
  3. If restart fails: mark unhealthy, alert oncall
  4. Dependent services continue with fallback
  5. Operator manual intervention required
```

### Automatic Failover (Future: High Availability)
```
If service A fails and Service B is replica:
  1. Detect failure within health_check_interval
  2. Switch load balancer to Service B
  3. Service A remains down (no active requests)
  4. Operator alerted for investigation
  5. Service A restarted automatically
```

### Circuit Breaker Pattern
```
If service continuously fails requests:
  1. Open circuit (stop sending requests)
  2. Return cached response or error
  3. Periodically test recovery (half-open state)
  4. Close circuit when service recovers
  5. Log circuit state transitions
```

## Monitoring Best Practices

### For Operators
1. Check main dashboard every 30 minutes during business hours
2. Set up alerting email/Slack integration
3. Maintain runbook for each critical alert
4. Review metrics weekly for trends
5. Capacity planning based on growth metrics

### For Developers
1. Monitor metrics during deployments
2. Track latency of new features
3. Use health checks in integration tests
4. Profile services under load
5. Document performance baselines

### For Security
1. Monitor audit logs in real-time
2. Alert on repeated policy violations
3. Track tool execution patterns
4. Detect anomalies in access patterns
5. Generate compliance reports

---

**Heartbeat Version**: 1.0
**Effective Date**: 2026-02-08
**Last Updated**: 2026-02-08
