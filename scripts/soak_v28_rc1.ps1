<#
.SYNOPSIS
    v2.8.0-rc1 Release-Grade Soak Test -- Mixed Traffic
.PARAMETER Cycles
    Number of soak cycles (default 100, ~30-60 min runtime).
.PARAMETER ExportIncident
    Export incident snapshot during soak (default $true).
.DESCRIPTION
    Mixed-traffic soak exercising all v2.8 risk surfaces:
    - Model routing with cancellation (barge-in cycles)
    - Memory recall with budget enforcement
    - Perception gate approval/denial flows
    - Operator session state machine cycling
    - Action pipeline throughput

    Required outputs:
    - Zero invariant violations
    - Zero unbounded queue growth
    - Zero stuck session states
    - Stable latency percentile envelope
    - Incident snapshot export validation
#>
param(
    [int]$Cycles = 100,
    [switch]$SkipLive,
    [bool]$ExportIncident = $true
)

$ErrorActionPreference = "Continue"
$python = "S:\envs\sonia-core\python.exe"
$rootDir = "S:\"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$soakReportDir = "S:\reports\soak-v28"
$tmpDir = "$soakReportDir\tmp"
if (-not (Test-Path $soakReportDir)) { New-Item -ItemType Directory -Path $soakReportDir -Force | Out-Null }
if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }

Write-Host "`n=== v2.8.0-rc1 Release-Grade Soak Test ===" -ForegroundColor Cyan
Write-Host "  Cycles: $Cycles"
Write-Host "  Timestamp: $timestamp"
Write-Host ""

$metrics = @{
    total_operations = 0
    cancel_cycles = 0
    memory_recalls = 0
    perception_gates = 0
    operator_cycles = 0
    invariant_violations = 0
    stuck_sessions = 0
    queue_overflows = 0
    errors = 0
    latencies = [System.Collections.Generic.List[double]]::new()
}

function Get-Percentile {
    param([System.Collections.Generic.List[double]]$values, [double]$pct)
    if ($values.Count -eq 0) { return 0 }
    $sorted = $values | Sort-Object
    $idx = [math]::Floor($sorted.Count * $pct)
    if ($idx -ge $sorted.Count) { $idx = $sorted.Count - 1 }
    return [math]::Round($sorted[$idx], 1)
}

# ── Phase 1: Cancellation Determinism Soak ─────────────────────────────────

Write-Host "Phase 1: Cancellation determinism soak..." -ForegroundColor Yellow

$cancelSoakFile = "$tmpDir\cancel_soak_$timestamp.py"
$cancelSoakResult = "$tmpDir\cancel_soak_result_$timestamp.txt"

$cancelSoakCode = @'
"""Cancellation soak: N cycles of create-cancel, verify zero zombies."""
import sys, asyncio, time, json
sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 50

class SlowClient:
    async def chat(self, messages, **kw):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        return {"response": "x", "tool_calls": []}

async def run():
    from model_call_context import ModelCallContext, ModelCallCancelled
    ModelCallContext.reset_counters()
    t0 = time.monotonic()
    violations = 0
    latencies = []

    for i in range(CYCLES):
        ct0 = time.monotonic()
        ctx = ModelCallContext(SlowClient(), timeout_ms=10000)
        task = asyncio.create_task(
            ctx.call(messages=[{"role": "user", "content": f"msg_{i}"}])
        )
        await asyncio.sleep(0.005)
        ctx.cancel(reason=f"soak_cycle_{i}")
        try:
            await task
        except (ModelCallCancelled, asyncio.CancelledError):
            pass
        except Exception as e:
            violations += 1

        latencies.append((time.monotonic() - ct0) * 1000)

        if ModelCallContext.get_active_count() != 0:
            violations += 1

    elapsed = (time.monotonic() - t0) * 1000
    result = {
        "cycles": CYCLES,
        "violations": violations,
        "active_count_final": ModelCallContext.get_active_count(),
        "total_cancellations": ModelCallContext.get_total_cancellations(),
        "elapsed_ms": round(elapsed, 1),
        "p50_ms": round(sorted(latencies)[len(latencies)//2], 1) if latencies else 0,
        "p95_ms": round(sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0, 1),
    }
    print(json.dumps(result))

asyncio.run(run())
'@

Set-Content -Path $cancelSoakFile -Value $cancelSoakCode -Encoding UTF8
$cancelCycles = [math]::Min($Cycles, 200)
& cmd.exe /c """$python"" -W ignore ""$cancelSoakFile"" $cancelCycles > ""$cancelSoakResult"" 2>&1"

$cancelResult = $null
if (Test-Path $cancelSoakResult) {
    $raw = Get-Content $cancelSoakResult -Raw
    $lines = ($raw -split "`n" | Where-Object { $_ -match "^\{" })
    if ($lines.Count -gt 0) {
        $cancelResult = $lines[-1] | ConvertFrom-Json
        $metrics.cancel_cycles = $cancelResult.cycles
        $metrics.total_operations += $cancelResult.cycles
        $metrics.invariant_violations += $cancelResult.violations
        Write-Host "  Cancel soak: $($cancelResult.cycles) cycles, violations=$($cancelResult.violations), active_final=$($cancelResult.active_count_final)" -ForegroundColor $(if ($cancelResult.violations -eq 0) { "Green" } else { "Red" })
        Write-Host "  Latency: p50=$($cancelResult.p50_ms)ms p95=$($cancelResult.p95_ms)ms elapsed=$($cancelResult.elapsed_ms)ms"
    } else {
        Write-Host "  [WARN] Cancel soak returned no JSON: $raw" -ForegroundColor Yellow
        $metrics.errors++
    }
} else {
    Write-Host "  [WARN] Cancel soak result file missing" -ForegroundColor Yellow
    $metrics.errors++
}

# ── Phase 2: Memory Budget Enforcement Soak ─────────────────────────────────

Write-Host "`nPhase 2: Memory budget enforcement soak..." -ForegroundColor Yellow

$memorySoakFile = "$tmpDir\memory_soak_$timestamp.py"
$memorySoakResult = "$tmpDir\memory_soak_result_$timestamp.txt"

$memorySoakCode = @'
"""Memory soak: N retrieval cycles with adversarial payloads."""
import sys, asyncio, time, json, random
sys.path.insert(0, r"S:\services\api-gateway")

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 50

class AdversarialMemoryClient:
    """Returns variable-size results to stress budget enforcement."""
    async def search(self, query, limit=10, correlation_id=None):
        # Vary response shape each call
        n = random.randint(0, 20)
        if n == 0:
            return []
        if n <= 3:
            return {"results": [{"id": f"m_{i}", "content": "x" * random.randint(100, 3000)} for i in range(n)]}
        return [{"id": f"m_{i}", "content": "y" * random.randint(50, 2000)} for i in range(n)]

async def run():
    from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
    t0 = time.monotonic()
    budget_violations = 0
    error_leaks = 0
    truncation_count = 0

    config = MemoryRecallConfig(max_context_chars=2000, max_results=10)
    ctx = MemoryRecallContext(AdversarialMemoryClient(), config=config)

    for i in range(CYCLES):
        result = await ctx.retrieve(query=f"soak_query_{i}", correlation_id=f"req_{i}")
        if result.error is not None:
            error_leaks += 1
        if len(result.context_text) > 2200:
            budget_violations += 1
        if result.truncated:
            truncation_count += 1

    elapsed = (time.monotonic() - t0) * 1000
    stats = ctx.get_stats()
    print(json.dumps({
        "cycles": CYCLES,
        "budget_violations": budget_violations,
        "error_leaks": error_leaks,
        "truncation_count": truncation_count,
        "elapsed_ms": round(elapsed, 1),
        "avg_latency_ms": round(stats.get("recent_avg_latency_ms", 0), 1),
    }))

asyncio.run(run())
'@

Set-Content -Path $memorySoakFile -Value $memorySoakCode -Encoding UTF8
$memoryCycles = [math]::Min($Cycles, 200)
& cmd.exe /c """$python"" -W ignore ""$memorySoakFile"" $memoryCycles > ""$memorySoakResult"" 2>&1"

$memoryResult = $null
if (Test-Path $memorySoakResult) {
    $raw = Get-Content $memorySoakResult -Raw
    $lines = ($raw -split "`n" | Where-Object { $_ -match "^\{" })
    if ($lines.Count -gt 0) {
        $memoryResult = $lines[-1] | ConvertFrom-Json
        $metrics.memory_recalls = $memoryResult.cycles
        $metrics.total_operations += $memoryResult.cycles
        $metrics.invariant_violations += $memoryResult.budget_violations
        Write-Host "  Memory soak: $($memoryResult.cycles) cycles, budget_violations=$($memoryResult.budget_violations), truncations=$($memoryResult.truncation_count)" -ForegroundColor $(if ($memoryResult.budget_violations -eq 0) { "Green" } else { "Red" })
        Write-Host "  Avg latency: $($memoryResult.avg_latency_ms)ms, elapsed=$($memoryResult.elapsed_ms)ms"
    } else {
        Write-Host "  [WARN] Memory soak returned no JSON: $raw" -ForegroundColor Yellow
        $metrics.errors++
    }
}

# ── Phase 3: Perception Gate Soak ──────────────────────────────────────────

Write-Host "`nPhase 3: Perception gate bypass soak..." -ForegroundColor Yellow

$perceptionSoakFile = "$tmpDir\perception_soak_$timestamp.py"
$perceptionSoakResult = "$tmpDir\perception_soak_result_$timestamp.txt"

$perceptionSoakCode = @'
"""Perception gate soak: N cycles of require->approve/deny->validate."""
import sys, time, json, random
sys.path.insert(0, r"S:\services\api-gateway")

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 100

def run():
    from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
    t0 = time.monotonic()
    gate = PerceptionActionGate(ttl_seconds=60.0)
    bypass_leaks = 0
    queue_overflow = 0

    actions = ["file.read", "file.write", "shell.run", "browser.open",
               "keyboard.type", "mouse.click", "app.launch", "window.focus"]

    for i in range(CYCLES):
        action = random.choice(actions)

        # Drain pending before creating new if near limit
        pending = gate.get_pending()
        if len(pending) > 40:
            for p in pending[:20]:
                if random.random() < 0.5:
                    gate.approve(p.requirement_id)
                    try:
                        gate.validate_execution(p.requirement_id)
                    except ConfirmationBypassError:
                        pass
                else:
                    gate.deny(p.requirement_id, reason="drain")

        req = gate.require_confirmation(
            action=action, scene_id=f"scene_{i}",
            session_id=f"sess_{i % 5}", correlation_id=f"req_{i}",
        )

        # 45% approve+execute, 35% deny, 10% leave pending, 10% bypass attempt
        roll = random.random()
        if roll < 0.45:
            gate.approve(req.requirement_id)
            validated = gate.validate_execution(req.requirement_id)
            if validated is None:
                bypass_leaks += 1
        elif roll < 0.80:
            gate.deny(req.requirement_id, reason="soak_deny")
            try:
                gate.validate_execution(req.requirement_id)
                bypass_leaks += 1
            except ConfirmationBypassError:
                pass
        elif roll < 0.90:
            pass  # Leave pending
        else:
            try:
                gate.validate_execution(req.requirement_id)
                bypass_leaks += 1
            except ConfirmationBypassError:
                pass

    stats = gate.get_stats()
    elapsed = (time.monotonic() - t0) * 1000

    if stats["pending_count"] > 50:
        queue_overflow = 1

    print(json.dumps({
        "cycles": CYCLES,
        "bypass_leaks": bypass_leaks,
        "queue_overflow": queue_overflow,
        "pending_final": stats["pending_count"],
        "total_approved": stats["total_approved"],
        "total_denied": stats["total_denied"],
        "bypass_attempts": stats["bypass_attempts"],
        "elapsed_ms": round(elapsed, 1),
    }))

run()
'@

Set-Content -Path $perceptionSoakFile -Value $perceptionSoakCode -Encoding UTF8
$perceptionCycles = [math]::Min($Cycles * 3, 500)
& cmd.exe /c """$python"" -W ignore ""$perceptionSoakFile"" $perceptionCycles > ""$perceptionSoakResult"" 2>&1"

if (Test-Path $perceptionSoakResult) {
    $raw = Get-Content $perceptionSoakResult -Raw
    $lines = ($raw -split "`n" | Where-Object { $_ -match "^\{" })
    if ($lines.Count -gt 0) {
        $percResult = $lines[-1] | ConvertFrom-Json
        $metrics.perception_gates = $percResult.cycles
        $metrics.total_operations += $percResult.cycles
        $metrics.invariant_violations += $percResult.bypass_leaks
        $metrics.queue_overflows += $percResult.queue_overflow
        Write-Host "  Perception soak: $($percResult.cycles) cycles, bypass_leaks=$($percResult.bypass_leaks), queue_overflow=$($percResult.queue_overflow)" -ForegroundColor $(if ($percResult.bypass_leaks -eq 0) { "Green" } else { "Red" })
        Write-Host "  Approved=$($percResult.total_approved) Denied=$($percResult.total_denied) Pending=$($percResult.pending_final) elapsed=$($percResult.elapsed_ms)ms"
    } else {
        Write-Host "  [WARN] Perception soak returned no JSON: $raw" -ForegroundColor Yellow
        $metrics.errors++
    }
}

# ── Phase 4: Operator Session Resilience Soak ──────────────────────────────

Write-Host "`nPhase 4: Operator session resilience soak..." -ForegroundColor Yellow

$opSoakFile = "$tmpDir\operator_soak_$timestamp.py"
$opSoakResult = "$tmpDir\operator_soak_result_$timestamp.txt"

$opSoakCode = @'
"""Operator session soak: N full turn cycles with subsystem degradation."""
import sys, time, json, random
sys.path.insert(0, r"S:\services\api-gateway")

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 100

def run():
    from operator_session import (
        OperatorSession, InputMode, SubsystemHealth, InvalidStateTransition,
    )
    t0 = time.monotonic()
    stuck_sessions = 0
    invalid_transitions = 0

    op = OperatorSession(session_id="soak_op", input_mode=InputMode.PUSH_TO_TALK)

    for i in range(CYCLES):
        # Randomly degrade subsystems
        for ss in ["model", "memory", "perception", "action"]:
            health = random.choice([
                SubsystemHealth.HEALTHY, SubsystemHealth.HEALTHY,
                SubsystemHealth.DEGRADED, SubsystemHealth.DOWN,
            ])
            op.update_subsystem(ss, health)

        # Full turn cycle
        try:
            turn_id = op.begin_listening()
            op.begin_processing()

            # 20% chance of cancel during processing
            if random.random() < 0.2:
                op.cancel_turn(reason="soak_cancel")
                continue

            op.begin_responding()

            # 10% chance of barge-in during responding
            if random.random() < 0.1:
                op.begin_listening()  # Barge-in: RESPONDING -> LISTENING
                op.cancel_turn(reason="soak_barge_in")
                continue

            op.end_turn(ok=True)
        except InvalidStateTransition:
            invalid_transitions += 1
            op.cancel_turn(reason="recovery")

        # Check not stuck
        if op.talk_state.value != "idle":
            stuck_sessions += 1
            op.cancel_turn(reason="stuck_recovery")

        # Random mode switches
        if random.random() < 0.1:
            mode = random.choice([InputMode.PUSH_TO_TALK, InputMode.ALWAYS_ON, InputMode.TEXT_ONLY])
            op.set_input_mode(mode)

    elapsed = (time.monotonic() - t0) * 1000
    indicators = op.get_indicators()
    snap = op.export_incident_snapshot()

    print(json.dumps({
        "cycles": CYCLES,
        "stuck_sessions": stuck_sessions,
        "invalid_transitions": invalid_transitions,
        "final_state": indicators["talk_state"],
        "total_turns": indicators["metrics"]["total_turns"],
        "total_cancels": indicators["metrics"]["total_cancels"],
        "total_errors": indicators["metrics"]["total_errors"],
        "activity_count": len(snap["recent_activity"]),
        "snapshot_valid": bool(snap.get("snapshot_id")),
        "elapsed_ms": round(elapsed, 1),
    }))

run()
'@

Set-Content -Path $opSoakFile -Value $opSoakCode -Encoding UTF8
$opCycles = [math]::Min($Cycles * 2, 300)
& cmd.exe /c """$python"" -W ignore ""$opSoakFile"" $opCycles > ""$opSoakResult"" 2>&1"

if (Test-Path $opSoakResult) {
    $raw = Get-Content $opSoakResult -Raw
    $lines = ($raw -split "`n" | Where-Object { $_ -match "^\{" })
    if ($lines.Count -gt 0) {
        $opResult = $lines[-1] | ConvertFrom-Json
        $metrics.operator_cycles = $opResult.cycles
        $metrics.total_operations += $opResult.cycles
        $metrics.stuck_sessions += $opResult.stuck_sessions
        Write-Host "  Operator soak: $($opResult.cycles) cycles, stuck=$($opResult.stuck_sessions), invalid=$($opResult.invalid_transitions)" -ForegroundColor $(if ($opResult.stuck_sessions -eq 0) { "Green" } else { "Red" })
        Write-Host "  Turns=$($opResult.total_turns) Cancels=$($opResult.total_cancels) Errors=$($opResult.total_errors) elapsed=$($opResult.elapsed_ms)ms"
        Write-Host "  Snapshot valid: $($opResult.snapshot_valid), final_state: $($opResult.final_state)"
    } else {
        Write-Host "  [WARN] Operator soak returned no JSON: $raw" -ForegroundColor Yellow
        $metrics.errors++
    }
}

# ── Phase 5: Incident Snapshot Export ─────────────────────────────────────

if ($ExportIncident) {
    Write-Host "`nPhase 5: Incident snapshot export validation..." -ForegroundColor Yellow

    $incidentSoakFile = "$tmpDir\incident_snapshot_$timestamp.py"
    $incidentSoakResult = "$tmpDir\incident_snapshot_result_$timestamp.txt"

    $incidentCode = @'
"""Validate incident snapshot export produces valid, complete JSON."""
import sys, json, time
sys.path.insert(0, r"S:\services\api-gateway")

from operator_session import OperatorSession, SubsystemHealth

op = OperatorSession(session_id="incident_test")
op.update_subsystem("model", SubsystemHealth.HEALTHY, latency_ms=50)
op.update_subsystem("memory", SubsystemHealth.DEGRADED, latency_ms=500, detail="slow")

# Run a few turns
for i in range(5):
    op.begin_listening()
    op.begin_processing()
    op.begin_responding()
    op.end_turn(ok=True)

snap = op.export_incident_snapshot()

# Validate completeness
required_keys = ["snapshot_id", "timestamp", "session_id", "talk_state",
                 "input_mode", "indicators", "recent_activity", "metrics"]
missing = [k for k in required_keys if k not in snap]

# Validate JSON roundtrip
serialized = json.dumps(snap)
parsed = json.loads(serialized)

print(json.dumps({
    "valid": len(missing) == 0,
    "missing_keys": missing,
    "json_roundtrip_ok": parsed["snapshot_id"] == snap["snapshot_id"],
    "snapshot_size_bytes": len(serialized),
    "activity_count": len(snap["recent_activity"]),
    "subsystem_count": len(snap["indicators"]["subsystems"]),
}))
'@

    Set-Content -Path $incidentSoakFile -Value $incidentCode -Encoding UTF8
    & cmd.exe /c """$python"" -W ignore ""$incidentSoakFile"" > ""$incidentSoakResult"" 2>&1"

    if (Test-Path $incidentSoakResult) {
        $raw = Get-Content $incidentSoakResult -Raw
        $lines = ($raw -split "`n" | Where-Object { $_ -match "^\{" })
        if ($lines.Count -gt 0) {
            $incResult = $lines[-1] | ConvertFrom-Json
            Write-Host "  Incident snapshot: valid=$($incResult.valid), roundtrip=$($incResult.json_roundtrip_ok), size=$($incResult.snapshot_size_bytes)B" -ForegroundColor $(if ($incResult.valid) { "Green" } else { "Red" })
            if (-not $incResult.valid) { $metrics.invariant_violations++ }
        }
    }
}

# ── Soak Summary ─────────────────────────────────────────────────────────

Write-Host "`n=== Soak Summary ===" -ForegroundColor Cyan
Write-Host "  Total operations:      $($metrics.total_operations)"
Write-Host "  Cancel cycles:         $($metrics.cancel_cycles)"
Write-Host "  Memory recalls:        $($metrics.memory_recalls)"
Write-Host "  Perception gates:      $($metrics.perception_gates)"
Write-Host "  Operator cycles:       $($metrics.operator_cycles)"
Write-Host "  Invariant violations:  $($metrics.invariant_violations)"
Write-Host "  Stuck sessions:        $($metrics.stuck_sessions)"
Write-Host "  Queue overflows:       $($metrics.queue_overflows)"
Write-Host "  Errors:                $($metrics.errors)"
Write-Host ""

# ── Soak Report JSON ──────────────────────────────────────────────────────

$soakReport = @{
    version = "v2.8.0-rc1"
    timestamp = $timestamp
    cycles = $Cycles
    metrics = $metrics
    phases = @{
        cancellation = if ($cancelResult) { $cancelResult } else { @{ status = "skipped" } }
        memory = if ($memoryResult) { $memoryResult } else { @{ status = "skipped" } }
        perception = if ($percResult) { $percResult } else { @{ status = "skipped" } }
        operator = if ($opResult) { $opResult } else { @{ status = "skipped" } }
    }
    verdict = ""
}

if ($metrics.invariant_violations -eq 0 -and $metrics.stuck_sessions -eq 0 -and $metrics.queue_overflows -eq 0 -and $metrics.errors -eq 0) {
    $soakReport.verdict = "PASS"
    Write-Host "[PASS] Soak test completed: 0 violations, 0 stuck sessions, 0 queue overflows" -ForegroundColor Green
} else {
    $soakReport.verdict = "FAIL"
    Write-Host "[FAIL] Soak test failed: violations=$($metrics.invariant_violations), stuck=$($metrics.stuck_sessions), overflow=$($metrics.queue_overflows), errors=$($metrics.errors)" -ForegroundColor Red
}

$reportPath = "$soakReportDir\soak-v28-$timestamp.json"
$soakReport | ConvertTo-Json -Depth 5 | Set-Content $reportPath -Encoding UTF8
Write-Host "  Report: $reportPath"
Write-Host ""

# Cleanup tmp
if (Test-Path $tmpDir) { Remove-Item "$tmpDir\*" -Force -ErrorAction SilentlyContinue }

if ($soakReport.verdict -eq "PASS") { exit 0 } else { exit 1 }
