"""
v2.8.0-rc1 Release-Grade Soak Runner

Single Python process running all soak phases:
  1. Cancellation determinism
  2. Memory budget enforcement
  3. Perception gate bypass
  4. Operator session resilience
  5. Incident snapshot validation

Outputs JSON report to stdout.
"""

import sys
import asyncio
import time
import json
import random
import uuid
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 100


# ── Mock Clients ─────────────────────────────────────────────────────────

class SlowRouterClient:
    async def chat(self, messages, **kw):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        return {"response": "x", "tool_calls": []}


class AdversarialMemoryClient:
    async def search(self, query, limit=10, correlation_id=None):
        n = random.randint(0, 20)
        if n == 0:
            return []
        if n <= 3:
            return {"results": [
                {"id": f"m_{i}", "content": "x" * random.randint(100, 3000)}
                for i in range(n)
            ]}
        return [
            {"id": f"m_{i}", "content": "y" * random.randint(50, 2000)}
            for i in range(n)
        ]


# ── Phase 1: Cancellation Determinism ──────────────────────────────────

async def phase_cancellation(cycles):
    from model_call_context import ModelCallContext, ModelCallCancelled

    ModelCallContext.reset_counters()
    t0 = time.monotonic()
    violations = 0
    latencies = []

    for i in range(cycles):
        ct0 = time.monotonic()
        ctx = ModelCallContext(SlowRouterClient(), timeout_ms=10000)
        task = asyncio.create_task(
            ctx.call(messages=[{"role": "user", "content": f"msg_{i}"}])
        )
        await asyncio.sleep(0.005)
        ctx.cancel(reason=f"soak_cycle_{i}")
        try:
            await task
        except (ModelCallCancelled, asyncio.CancelledError):
            pass
        except Exception:
            violations += 1

        latencies.append((time.monotonic() - ct0) * 1000)

        if ModelCallContext.get_active_count() != 0:
            violations += 1

    elapsed = (time.monotonic() - t0) * 1000
    lat_sorted = sorted(latencies) if latencies else [0]

    return {
        "cycles": cycles,
        "violations": violations,
        "active_count_final": ModelCallContext.get_active_count(),
        "total_cancellations": ModelCallContext.get_total_cancellations(),
        "elapsed_ms": round(elapsed, 1),
        "p50_ms": round(lat_sorted[len(lat_sorted) // 2], 1),
        "p95_ms": round(lat_sorted[int(len(lat_sorted) * 0.95)], 1),
    }


# ── Phase 2: Memory Budget Enforcement ─────────────────────────────────

async def phase_memory(cycles):
    from memory_recall_context import MemoryRecallContext, MemoryRecallConfig

    t0 = time.monotonic()
    budget_violations = 0
    error_leaks = 0
    truncation_count = 0

    config = MemoryRecallConfig(max_context_chars=2000, max_results=10)
    ctx = MemoryRecallContext(AdversarialMemoryClient(), config=config)

    for i in range(cycles):
        result = await ctx.retrieve(query=f"soak_query_{i}", correlation_id=f"req_{i}")
        if result.error is not None:
            error_leaks += 1
        if len(result.context_text) > 2200:
            budget_violations += 1
        if result.truncated:
            truncation_count += 1

    elapsed = (time.monotonic() - t0) * 1000
    stats = ctx.get_stats()

    return {
        "cycles": cycles,
        "budget_violations": budget_violations,
        "error_leaks": error_leaks,
        "truncation_count": truncation_count,
        "elapsed_ms": round(elapsed, 1),
        "avg_latency_ms": round(stats.get("recent_avg_latency_ms", 0), 2),
    }


# ── Phase 3: Perception Gate ───────────────────────────────────────────

def phase_perception(cycles):
    from perception_action_gate import PerceptionActionGate, ConfirmationBypassError

    t0 = time.monotonic()
    gate = PerceptionActionGate(ttl_seconds=60.0)
    bypass_leaks = 0
    queue_overflow = 0

    actions = ["file.read", "file.write", "shell.run", "browser.open",
               "keyboard.type", "mouse.click", "app.launch", "window.focus"]

    for i in range(cycles):
        action = random.choice(actions)

        # Drain pending if near limit
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

    return {
        "cycles": cycles,
        "bypass_leaks": bypass_leaks,
        "queue_overflow": queue_overflow,
        "pending_final": stats["pending_count"],
        "total_approved": stats["total_approved"],
        "total_denied": stats["total_denied"],
        "bypass_attempts": stats["bypass_attempts"],
        "elapsed_ms": round(elapsed, 1),
    }


# ── Phase 4: Operator Session ──────────────────────────────────────────

def phase_operator(cycles):
    from operator_session import (
        OperatorSession, InputMode, SubsystemHealth, InvalidStateTransition,
    )

    t0 = time.monotonic()
    stuck_sessions = 0
    invalid_transitions = 0

    op = OperatorSession(session_id="soak_op", input_mode=InputMode.PUSH_TO_TALK)

    for i in range(cycles):
        for ss in ["model", "memory", "perception", "action"]:
            health = random.choice([
                SubsystemHealth.HEALTHY, SubsystemHealth.HEALTHY,
                SubsystemHealth.DEGRADED, SubsystemHealth.DOWN,
            ])
            op.update_subsystem(ss, health)

        try:
            op.begin_listening()
            op.begin_processing()

            if random.random() < 0.2:
                op.cancel_turn(reason="soak_cancel")
                continue

            op.begin_responding()

            if random.random() < 0.1:
                op.begin_listening()
                op.cancel_turn(reason="soak_barge_in")
                continue

            op.end_turn(ok=True)
        except InvalidStateTransition:
            invalid_transitions += 1
            op.cancel_turn(reason="recovery")

        if op.talk_state.value != "idle":
            stuck_sessions += 1
            op.cancel_turn(reason="stuck_recovery")

        if random.random() < 0.1:
            mode = random.choice([
                InputMode.PUSH_TO_TALK, InputMode.ALWAYS_ON, InputMode.TEXT_ONLY,
            ])
            op.set_input_mode(mode)

    elapsed = (time.monotonic() - t0) * 1000
    indicators = op.get_indicators()
    snap = op.export_incident_snapshot()

    return {
        "cycles": cycles,
        "stuck_sessions": stuck_sessions,
        "invalid_transitions": invalid_transitions,
        "final_state": indicators["talk_state"],
        "total_turns": indicators["metrics"]["total_turns"],
        "total_cancels": indicators["metrics"]["total_cancels"],
        "total_errors": indicators["metrics"]["total_errors"],
        "activity_count": len(snap["recent_activity"]),
        "snapshot_valid": bool(snap.get("snapshot_id")),
        "elapsed_ms": round(elapsed, 1),
    }


# ── Phase 5: Incident Snapshot ──────────────────────────────────────────

def phase_incident():
    from operator_session import OperatorSession, SubsystemHealth

    op = OperatorSession(session_id="incident_test")
    op.update_subsystem("model", SubsystemHealth.HEALTHY, latency_ms=50)
    op.update_subsystem("memory", SubsystemHealth.DEGRADED, latency_ms=500, detail="slow")

    for i in range(5):
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn(ok=True)

    snap = op.export_incident_snapshot()
    required_keys = ["snapshot_id", "timestamp", "session_id", "talk_state",
                     "input_mode", "indicators", "recent_activity", "metrics"]
    missing = [k for k in required_keys if k not in snap]
    serialized = json.dumps(snap)
    parsed = json.loads(serialized)

    return {
        "valid": len(missing) == 0,
        "missing_keys": missing,
        "json_roundtrip_ok": parsed["snapshot_id"] == snap["snapshot_id"],
        "snapshot_size_bytes": len(serialized),
        "activity_count": len(snap["recent_activity"]),
        "subsystem_count": len(snap["indicators"]["subsystems"]),
    }


# ── Main ──────────────────────────────────────────────────────────────

async def main():
    t0 = time.monotonic()

    print("Phase 1: Cancellation determinism...", file=sys.stderr)
    cancel_result = await phase_cancellation(min(CYCLES, 200))

    print("Phase 2: Memory budget enforcement...", file=sys.stderr)
    memory_result = await phase_memory(min(CYCLES, 200))

    print("Phase 3: Perception gate bypass...", file=sys.stderr)
    perception_result = phase_perception(min(CYCLES * 3, 500))

    print("Phase 4: Operator session resilience...", file=sys.stderr)
    operator_result = phase_operator(min(CYCLES * 2, 300))

    print("Phase 5: Incident snapshot...", file=sys.stderr)
    incident_result = phase_incident()

    total_elapsed = (time.monotonic() - t0) * 1000

    total_ops = (
        cancel_result["cycles"]
        + memory_result["cycles"]
        + perception_result["cycles"]
        + operator_result["cycles"]
    )

    invariant_violations = (
        cancel_result["violations"]
        + memory_result["budget_violations"]
        + perception_result["bypass_leaks"]
    )

    stuck_sessions = operator_result["stuck_sessions"]
    queue_overflows = perception_result["queue_overflow"]

    verdict = "PASS" if (
        invariant_violations == 0
        and stuck_sessions == 0
        and queue_overflows == 0
        and incident_result["valid"]
    ) else "FAIL"

    report = {
        "version": "v2.8.0-rc1",
        "timestamp": time.strftime("%Y%m%d-%H%M%S"),
        "cycles": CYCLES,
        "total_operations": total_ops,
        "total_elapsed_ms": round(total_elapsed, 1),
        "invariant_violations": invariant_violations,
        "stuck_sessions": stuck_sessions,
        "queue_overflows": queue_overflows,
        "verdict": verdict,
        "phases": {
            "cancellation": cancel_result,
            "memory": memory_result,
            "perception": perception_result,
            "operator": operator_result,
            "incident": incident_result,
        },
    }

    # Output JSON to stdout (only valid JSON)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
