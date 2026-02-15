# TROUBLESHOOTING

Decision tree format for diagnosing and resolving SONIA issues.

## Service Won't Start

```
1. Check if Python environment exists
   Test: Test-Path S:\envs\sonia-core\python.exe
   ├─ NO -> Create conda environment (see DEPLOYMENT.md)
   └─ YES -> Continue to step 2

2. Check if port is already in use
   Test: Get-NetTCPConnection -LocalPort <PORT> -State Listen
   ├─ Port in use by Sonia service -> Service already running, skip
   ├─ Port in use by other process -> Kill other process or change port in config
   └─ Port available -> Continue to step 3

3. Check service-specific dependencies
   For api-gateway, model-router, memory-engine, pipecat, openclaw, eva-os:
   Test: cd S:\services\<service>; S:\envs\sonia-core\python.exe -c "import fastapi, uvicorn"
   ├─ ImportError -> Run: pip install -r requirements.txt
   └─ Success -> Continue to step 4

4. Check startup script exists
   Test: Test-Path S:\scripts\ops\run-<service>.ps1
   ├─ NO -> Create script or use manual start (see OPERATIONS_RUNBOOK.md)
   └─ YES -> Continue to step 5

5. Check for stderr errors
   Action: Start service and immediately tail stderr
   Test: Start service; Get-Content S:\logs\services\<service>.err.log -Wait -Tail 20
   ├─ ImportError -> Missing Python dependency, run pip install
   ├─ "Address already in use" -> Port conflict, see step 2
   ├─ "Config not found" -> Check S:\config\sonia-config.json exists
   ├─ "Database locked" -> See "Database Locked" tree below
   └─ Other error -> Read full traceback, file incident bundle

6. Check PID file cleanup
   Test: Test-Path S:\state\pids\<service>.pid
   ├─ Stale PID file exists -> Remove: Remove-Item S:\state\pids\<service>.pid -Force
   └─ No PID file -> Continue to step 7

7. Manual start with verbose output
   Action: cd S:\services\<service>
   Action: S:\envs\sonia-core\python.exe -m uvicorn main:app --host 127.0.0.1 --port <PORT>
   ├─ Starts successfully -> Startup script issue, debug script
   ├─ Crashes immediately -> Application error, check code
   └─ Hangs -> Deadlock or blocking call, check lifespan events

Resolution: If all steps pass but service still won't start, export incident bundle and file issue.
```

## Health Check Failing

```
1. Check if service port is listening
   Test: Test-NetConnection -ComputerName 127.0.0.1 -Port <PORT>
   ├─ Connection failed -> Service not running, see "Service Won't Start" tree
   └─ Connection succeeded -> Continue to step 2

2. Check /healthz endpoint manually
   Test: iwr http://127.0.0.1:<PORT>/healthz
   ├─ 200 OK -> Service healthy, check health check script logic
   ├─ 500 Internal Server Error -> Service unhealthy, see step 3
   ├─ 404 Not Found -> Wrong endpoint, verify /healthz exists in code
   └─ Timeout -> Service hung, see step 5

3. Check service-specific health dependencies
   For api-gateway:
      Test: iwr http://127.0.0.1:7010/healthz (model-router)
      Test: iwr http://127.0.0.1:7020/healthz (memory-engine)
      ├─ Downstream unhealthy -> Fix downstream first
      └─ Downstream healthy -> Continue to step 4

   For model-router:
      Test: iwr http://127.0.0.1:11434/api/tags (Ollama)
      ├─ Ollama unreachable -> Start Ollama, verify models loaded
      └─ Ollama healthy -> Continue to step 4

   For memory-engine:
      Test: sqlite3 S:\data\memory.db "SELECT 1;"
      ├─ Database locked -> See "Database Locked" tree
      ├─ Database not found -> Initialize DB (restart memory-engine)
      └─ Database accessible -> Continue to step 4

4. Check stderr for health check errors
   Test: Get-Content S:\logs\services\<service>.err.log -Tail 50
   ├─ "Connection refused" to downstream -> Downstream service not running
   ├─ "Timeout" to downstream -> Downstream service hung or slow
   ├─ Database error -> See "Database Locked" tree
   └─ Other error -> Read traceback, fix application code

5. Check if service is hung
   Test: Get-Process | Where-Object { $_.ProcessName -eq "python" }
   Action: Check CPU usage (should be <10% at idle)
   ├─ CPU at 100% -> Infinite loop or deadlock, restart service
   ├─ CPU at 0% -> Blocked on I/O, check for network timeouts
   └─ CPU normal but not responding -> Restart service

6. Check circuit breaker state (api-gateway only)
   Test: iwr http://127.0.0.1:7000/v1/breakers/metrics
   ├─ Breaker OPEN -> See "Circuit Breaker Stuck OPEN" tree
   └─ Breaker CLOSED -> Continue to step 7

7. Restart service with clean state
   Action: Stop service
   Action: Remove PID file: Remove-Item S:\state\pids\<service>.pid -Force
   Action: Start service
   Test: Wait-SoniaServiceHealth -Port <PORT> -MaxWaitSeconds 30
   ├─ Health check passes -> Transient issue, monitor
   └─ Health check fails -> Persistent issue, export incident bundle

Resolution: If health check still failing, check disk space, memory, GPU VRAM.
```

## Memory Search Returns Nothing

```
1. Check if database is empty
   Test: sqlite3 S:\data\memory.db "SELECT COUNT(*) FROM memories WHERE archived_at IS NULL;"
   ├─ Count = 0 -> No active memories, write some data first
   └─ Count > 0 -> Continue to step 2

2. Check search query syntax
   LIKE search (default): Requires literal substring match
   Test: iwr "http://127.0.0.1:7020/v1/memory/search?query=test&limit=10"
   ├─ Query is substring of content -> Should return results, continue to step 3
   └─ Query is not exact substring -> No results expected, try BM25

3. Try BM25 search (more fuzzy)
   Test: iwr -Method POST http://127.0.0.1:7020/v1/memory/search -ContentType "application/json" -Body '{"query":"test","limit":10,"use_bm25":true}'
   ├─ Returns results -> LIKE search too strict, use BM25
   └─ Still no results -> Continue to step 4

4. Check user_id filter
   Test: sqlite3 S:\data\memory.db "SELECT DISTINCT user_id FROM memories WHERE archived_at IS NULL;"
   Action: Verify query user_id matches database user_id
   ├─ user_id mismatch -> Update query to correct user_id
   └─ user_id matches -> Continue to step 5

5. Check archived_at filter
   Test: sqlite3 S:\data\memory.db "SELECT COUNT(*) FROM memories WHERE content LIKE '%test%';"
   Action: Compare with count from step 1
   ├─ Archived count > Active count -> Memories soft-deleted, restore if needed
   └─ Counts match -> Continue to step 6

6. Check memory_type filter
   Test: iwr "http://127.0.0.1:7020/v1/memory/search?query=test&memory_types=FACT,OBSERVATION&limit=10"
   Action: Verify query memory_types includes expected types
   ├─ type filter too restrictive -> Remove type filter or add types
   └─ type filter correct -> Continue to step 7

7. Check database not corrupted
   Test: sqlite3 S:\data\memory.db "PRAGMA integrity_check;"
   ├─ Errors reported -> Database corrupted, restore from backup
   └─ "ok" -> Database intact, continue to step 8

8. Check token budget limits
   Test: iwr "http://127.0.0.1:7020/v1/memory/search?query=test&limit=100" (increase limit)
   ├─ Returns results with higher limit -> Token budget too low, increase limit
   └─ Still no results -> Export incident bundle, manual SQL investigation

Resolution: If no results and all steps pass, check for encoding issues (UTF-8 vs ASCII).
```

## DLQ Growing

```
1. Check DLQ depth
   Test: iwr http://127.0.0.1:7000/v1/dead-letters | ConvertFrom-Json | Measure-Object | Select-Object Count
   ├─ Count = 0 -> DLQ empty, false alarm
   └─ Count > 0 -> Continue to step 2

2. Identify failure class
   Test: iwr http://127.0.0.1:7000/v1/dead-letters | ConvertFrom-Json | Group-Object failure_class
   Classes: CONNECTION_BOOTSTRAP, TIMEOUT, CIRCUIT_OPEN, POLICY_DENIED, VALIDATION_FAILED, EXECUTION_ERROR, BACKPRESSURE, UNKNOWN
   Action: Note most common failure_class
   -> Continue to step 3 (class-specific remediation)

3. Remediate by failure class

   CONNECTION_BOOTSTRAP:
      Cause: Downstream service (openclaw, model-router) not reachable
      Test: iwr http://127.0.0.1:7040/healthz (openclaw)
      Test: iwr http://127.0.0.1:7010/healthz (model-router)
      ├─ Downstream unhealthy -> Restart downstream service
      └─ Downstream healthy -> Check network config, firewall

   TIMEOUT:
      Cause: Tool execution or model inference too slow
      Test: Get-Content S:\logs\gateway\turns.jsonl | ConvertFrom-Json | Select-Object -Last 20 -Property latency_ms
      ├─ model_ms > 10000 -> Model too slow, switch to faster model in config
      ├─ tool_ms > 5000 -> Tool execution slow, check tool implementation
      └─ total_ms normal -> Timeout threshold too low, increase timeout in config

   CIRCUIT_OPEN:
      Cause: Circuit breaker tripped due to repeated failures
      Test: iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json
      Action: See "Circuit Breaker Stuck OPEN" tree
      Resolution: Fix underlying issue, breaker will auto-close

   POLICY_DENIED:
      Cause: Tool safety policy blocked execution
      Test: Get-Content S:\logs\gateway\tools.jsonl | ConvertFrom-Json | Where-Object { $_.verdict -eq "deny" }
      ├─ Capability blocked in policy -> Update tool_policy.py to allow
      ├─ User denied confirmation -> Expected behavior, no action
      └─ Path traversal attempt -> Security incident, audit logs

   VALIDATION_FAILED:
      Cause: Tool arguments invalid (schema validation failed)
      Test: Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Where-Object { $_.failure_class -eq "VALIDATION_FAILED" }
      Action: Read error_message for specific validation failure
      ├─ Missing required arg -> Fix tool call in model prompt
      ├─ Type mismatch -> Fix schema or tool implementation
      └─ Path outside root -> Fix root contract validation

   EXECUTION_ERROR:
      Cause: Tool execution failed (exception raised)
      Test: Get-Content S:\logs\gateway\tools.jsonl | ConvertFrom-Json | Where-Object { $_.result -like "*error*" }
      Action: Read tool execution traceback
      ├─ File not found -> Fix file path in tool call
      ├─ Permission denied -> Fix file system permissions
      ├─ Disk full -> Free up disk space
      └─ Other exception -> Debug tool implementation

   BACKPRESSURE:
      Cause: Too many concurrent requests, rate limiting active
      Test: iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json
      Action: Check request rate, reduce concurrency
      Resolution: Wait for rate limit cooldown, or increase capacity in config

   UNKNOWN:
      Cause: Unclassified failure (catch-all)
      Test: Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Where-Object { $_.failure_class -eq "UNKNOWN" }
      Action: Read full error message and traceback
      Resolution: File issue with full context

4. Replay DLQ entries (after fix)
   Test: iwr -Method POST "http://127.0.0.1:7000/v1/dead-letters/<ID>/replay?dry_run=true"
   ├─ Dry-run succeeds -> Replay: iwr -Method POST "http://127.0.0.1:7000/v1/dead-letters/<ID>/replay"
   └─ Dry-run fails -> Root cause not fixed, continue debugging

5. Purge unrecoverable entries
   Action: iwr -Method DELETE "http://127.0.0.1:7000/v1/dead-letters/<ID>"
   Use case: Entries with invalid data, obsolete requests, or permanent failures

Resolution: If DLQ continues growing after remediation, increase retry limits or disable retries.
```

## Circuit Breaker Stuck OPEN

```
1. Check breaker state
   Test: iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json
   Fields: state (CLOSED/OPEN/HALF_OPEN), failure_count, last_failure_time, recovery_probes
   ├─ State = CLOSED -> Not stuck, false alarm
   ├─ State = HALF_OPEN -> Testing recovery, wait 30s for result
   └─ State = OPEN -> Continue to step 2

2. Check failure window
   Test: Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Where-Object { $_.capability -eq "<CAPABILITY>" -and $_.timestamp -gt (Get-Date).AddMinutes(-5) }
   Action: Count failures in last 5 minutes
   ├─ Failure count >= threshold (default 3) -> Breaker correctly OPEN, fix root cause
   └─ Failure count < threshold -> Breaker state stale, continue to step 3

3. Identify root cause
   Test: Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Select-Object -Last 10 -Property capability, error_message, failure_class
   Common causes:
   ├─ CONNECTION_BOOTSTRAP -> Downstream service down, restart service
   ├─ TIMEOUT -> Increase timeout or optimize tool implementation
   ├─ EXECUTION_ERROR -> Fix tool bug (permissions, disk space, etc.)
   └─ VALIDATION_FAILED -> Fix tool arguments or schema

4. Fix root cause and wait for HALF_OPEN transition
   Default quarantine: 30 seconds
   Action: Wait for breaker to enter HALF_OPEN state
   Test: iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json | Select-Object state
   ├─ State = HALF_OPEN -> Continue to step 5
   └─ State = OPEN after 60s -> Breaker not transitioning, restart api-gateway

5. Test recovery probe
   Action: Send single request to trigger recovery probe
   Test: iwr -Method POST http://127.0.0.1:7000/v1/actions -ContentType "application/json" -Body '{...}'
   ├─ Request succeeds -> Breaker enters CLOSED, recovery successful
   ├─ Request fails -> Breaker returns to OPEN, root cause not fixed
   └─ No response -> Service hung, restart service

6. Verify breaker CLOSED
   Test: iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json | Select-Object state, recovery_probes
   ├─ recovery_probes >= 2 and state = CLOSED -> Success
   └─ State still OPEN -> Repeat from step 3

Resolution: If breaker cannot close after multiple attempts, disable capability or restart api-gateway.
```

## High Latency

```
1. Check latency breakdown in JSONL
   Test: Get-Content S:\logs\gateway\turns.jsonl | ConvertFrom-Json | Select-Object -Last 20 -Property latency_ms
   Fields: total, memory_read, model, tool, memory_write, asr, vision
   Action: Identify highest latency component
   -> Continue to component-specific troubleshooting

2. Model latency high (model_ms > 2000)
   Causes: Large context, slow model, GPU memory contention
   Test: nvidia-smi dmon -c 10
   ├─ GPU utilization 100% -> Model inference bottleneck, continue to 2a
   ├─ GPU memory >90% full -> VRAM exhausted, continue to 2b
   └─ GPU idle -> Model not using GPU, check CUDA installation

   2a. Model inference bottleneck:
      Action: Switch to faster model in config
      Test: Check model_router.profiles.backend_capacities for avg_latency_ms
      ├─ Use ollama/qwen2.5:7b (800ms avg) instead of sonia-vlm:32b (2000ms avg)
      └─ Or use cloud model (anthropic/claude-haiku-4-5, 500ms avg)

   2b. VRAM exhausted:
      Test: nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits
      ├─ <4GB free -> Unload unused models: ollama rm <model>
      └─ Or restart Ollama to clear VRAM: Restart-Service Ollama

3. Memory read latency high (memory_read_ms > 500)
   Causes: Large database, slow disk, inefficient query
   Test: sqlite3 S:\data\memory.db "SELECT page_count * page_size / 1024 / 1024 FROM pragma_page_count(), pragma_page_size();"
   ├─ DB size > 500MB -> VACUUM database: sqlite3 S:\data\memory.db "VACUUM;"
   └─ DB size normal -> Continue to 3a

   3a. Check query efficiency:
      Test: sqlite3 S:\data\memory.db "EXPLAIN QUERY PLAN SELECT * FROM memories WHERE user_id = 'X' AND archived_at IS NULL;"
      ├─ "SCAN TABLE memories" (no index) -> Create index: CREATE INDEX idx_user_archived ON memories(user_id, archived_at);
      └─ "SEARCH TABLE memories USING INDEX" -> Index used, continue to 3b

   3b. Check disk I/O:
      Test: Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object -Property DeviceId, ReadLatency, WriteLatency
      ├─ Latency > 50ms -> Slow disk (HDD?), migrate to SSD
      └─ Latency normal -> Archive old data to reduce DB size

4. Tool execution latency high (tool_ms > 1000)
   Causes: Slow tool implementation, blocking I/O, subprocess overhead
   Test: Get-Content S:\logs\gateway\tools.jsonl | ConvertFrom-Json | Select-Object -Last 20 -Property capability, execution_time_ms
   ├─ shell.run slow -> Subprocess overhead, use ctypes adapter for simple operations
   ├─ file.write slow -> Check disk I/O (step 3b)
   └─ Other tool slow -> Profile tool code, optimize

5. Network latency between services
   Test: Measure-Command { iwr http://127.0.0.1:7010/healthz }
   ├─ >100ms -> Windows Firewall inspecting localhost traffic, add exception
   └─ <100ms -> Not network latency, check application logic

6. Check for concurrent request saturation
   Test: Get-Content S:\logs\gateway\turns.jsonl | ConvertFrom-Json | Group-Object -Property timestamp | Where-Object { $_.Count -gt 5 }
   ├─ >10 concurrent requests -> Rate limiting or queue backpressure, reduce concurrency
   └─ <10 concurrent -> Not saturation, check other factors

Resolution: If latency still high, check CPU usage (Get-Process python | Select-Object CPU).
```

## Database Locked

```
1. Check for long-running transactions
   Test: sqlite3 S:\data\memory.db "PRAGMA wal_checkpoint(TRUNCATE);"
   ├─ Error "database is locked" -> Continue to step 2
   └─ Success -> WAL checkpoint completed, restart memory-engine

2. Identify processes with open file handles
   Test: handle64 S:\data\memory.db
   Action: List all processes with open handles to memory.db
   ├─ Multiple python.exe processes -> Multiple instances running, kill duplicates
   ├─ sqlite3.exe or DB browser -> Close manual DB connections
   └─ Only memory-engine -> Continue to step 3

3. Stop all services to release locks
   Action: .\stop-sonia-stack.ps1
   Test: handle64 S:\data\memory.db
   ├─ Still locked -> Orphaned file handle, restart machine
   └─ No locks -> Continue to step 4

4. Run WAL checkpoint manually
   Test: sqlite3 S:\data\memory.db "PRAGMA wal_checkpoint(FULL);"
   ├─ Success -> WAL merged, continue to step 5
   └─ Error -> Database corrupted, restore from backup (see BACKUP_RECOVERY.md)

5. Verify database integrity
   Test: sqlite3 S:\data\memory.db "PRAGMA integrity_check;"
   ├─ "ok" -> Database intact, restart services
   └─ Errors -> Database corrupted, restore from backup

6. Restart services
   Action: .\start-sonia-stack.ps1
   Test: Wait-SoniaServiceHealth -Port 7020 -MaxWaitSeconds 30
   ├─ Memory-engine healthy -> Locks resolved
   └─ Still failing -> Export incident bundle, restore from backup

Resolution: If database repeatedly locks, reduce write concurrency or increase WAL checkpoint frequency.
```

## Known Limitations / Non-Goals

1. **No Automatic Recovery**: Manual troubleshooting required (no self-healing).
2. **No Remote Diagnostics**: Must have local machine access to troubleshoot.
3. **No Root Cause Analysis**: Logs provide symptoms, not automated RCA.
4. **No Alerting**: Manual log monitoring required (no proactive notifications).
5. **No Playbook Automation**: Decision trees are manual procedures (no runbook automation).
6. **No Performance Profiling**: No built-in APM or distributed tracing.
7. **No Chaos Engineering**: No automated fault injection or resilience testing.
8. **No Dependency Graphing**: Service dependencies not visualized (manual tracking).
9. **No Log Aggregation**: Each service logs separately (no centralized logging).
10. **No Interactive Debugger**: No built-in REPL or debug console for live troubleshooting.
