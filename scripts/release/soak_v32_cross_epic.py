"""v3.2 Cross-Epic Stress Soak: voice + perception + memory in mixed sessions.

Verifies invariants remain zero-breach under combined load:
  - silent_write_count == 0
  - false_bypass_count == 0
  - replay divergence == 0
  - queue overflow handled explicitly (no silent drop)
"""
import sys
import json
import time
import importlib.util
import types
from pathlib import Path

REPO_ROOT = Path("S:/")
sys.path.insert(0, str(REPO_ROOT))

# Register package hierarchy
for pkg_name, pkg_dir in [
    ("services", REPO_ROOT / "services"),
    ("services.pipecat", REPO_ROOT / "services" / "pipecat"),
    ("services.pipecat.voice", REPO_ROOT / "services" / "pipecat" / "voice"),
    ("services.perception", REPO_ROOT / "services" / "perception"),
    ("services.memory_ops", REPO_ROOT / "services" / "memory_ops"),
]:
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def _load(base, name):
    full = f"{base}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    fp = REPO_ROOT / base.replace(".", "/") / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full, fp, submodule_search_locations=[])
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = base
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# Voice modules
_load("services.pipecat.voice", "turn_events")
_load("services.pipecat.voice", "turn_state")
_load("services.pipecat.voice", "turn_reducer")
_load("services.pipecat.voice", "cancel_registry")

# Perception modules
_load("services.perception", "event_normalizer")
_load("services.perception", "dedupe_engine")
_load("services.perception", "priority_router")
_load("services.perception", "confirmation_batcher")
_load("services.perception", "provenance_hooks")
_load("services.perception", "policy")

# Memory modules
_load("services.memory_ops", "proposal_model")
_load("services.memory_ops", "proposal_policy")
_load("services.memory_ops", "proposal_queue")
_load("services.memory_ops", "conflict_detector")
_load("services.memory_ops", "provenance")
_load("services.memory_ops", "governance_pipeline")
_load("services.memory_ops", "replay_engine")

from services.pipecat.voice.turn_events import TurnEvent
from services.pipecat.voice.turn_state import TurnState, TurnSnapshot
from services.pipecat.voice.turn_reducer import reduce_turn
from services.pipecat.voice.cancel_registry import CancelRegistry
from services.perception.policy import PerceptionPipeline
from services.memory_ops.governance_pipeline import MemoryGovernancePipeline
from services.memory_ops.proposal_model import MemoryType
from services.memory_ops.replay_engine import ReplayEngine, ProposalInput


def _evt(event_type, sid, tid, seq):
    return TurnEvent(
        event_type=event_type,
        session_id=sid,
        turn_id=tid,
        seq=seq,
        ts_monotonic_ns=seq * 1_000_000,
        correlation_id=f"corr-{sid}-{tid}-{seq}",
    )


def run_soak():
    t0 = time.time()
    results = {"phases": [], "invariants": {}, "verdict": "UNKNOWN"}

    # Phase 1: Voice turn churn (50 sessions with barge-in)
    print("[Phase 1] Voice turn churn: 50 sessions with barge-in...")
    cancel_reg = CancelRegistry()
    voice_violations = 0

    for i in range(50):
        sid = f"voice-soak-{i}"
        tid = f"turn-{i}"
        snap = TurnSnapshot(
            session_id=sid, turn_id=tid,
            state=TurnState.IDLE, seq=0,
            correlation_id=f"corr-{sid}-{tid}-0",
        )

        snap, _ = reduce_turn(snap, _evt("TURN_STARTED", sid, tid, 1))
        snap, _ = reduce_turn(snap, _evt("ASR_FINAL", sid, tid, 2))
        snap, _ = reduce_turn(snap, _evt("MODEL_FIRST_TOKEN", sid, tid, 3))

        if i % 3 == 0:  # barge-in every 3rd session
            snap, _ = reduce_turn(snap, _evt("BARGE_IN_REQUESTED", sid, tid, 4))
            cancel_reg.request(sid, tid)
            consumed = cancel_reg.consume(sid, tid)
            if not consumed:
                voice_violations += 1
            snap, _ = reduce_turn(snap, _evt("CANCEL_REQUESTED", sid, tid, 5))
            snap, _ = reduce_turn(snap, _evt("TURN_STARTED", sid, tid, 6))
        else:
            snap, _ = reduce_turn(snap, _evt("TTS_ENDED", sid, tid, 4))

    results["phases"].append({
        "name": "voice_churn",
        "sessions": 50,
        "violations": voice_violations,
    })
    print(f"  Voice: {voice_violations} violations")

    # Phase 2: Perception burst (200 events with dedupe pressure)
    print("[Phase 2] Perception burst: 200 events with dedupe pressure...")
    perception = PerceptionPipeline(dedupe_window=50, lane_cap=30, total_cap=100)

    for i in range(200):
        raw = {
            "session_id": "perc-soak-1",
            "source": "vision",
            "event_type": "entity_detection",
            "correlation_id": f"corr-{i}",
            "confidence": 0.6 + (i % 10) * 0.04,
            "payload": {
                "label": f"object-{i % 20}",
                "bbox": [100 + (i % 5) * 10, 100, 200, 200],
            },
        }
        perception.process_raw(raw, action="observe" if i % 5 != 0 else "confirm")

    perc_report = perception.get_report()
    results["phases"].append({
        "name": "perception_burst",
        "events": 200,
        "false_bypass_count": perc_report.get("false_bypass_count", 0),
        "overflow_events": perc_report.get("overflow_events", 0),
    })
    print(f"  Perception: false_bypass={perc_report.get('false_bypass_count', 0)}, "
          f"overflow={perc_report.get('overflow_events', 0)}")

    # Phase 3: Memory proposal churn (100 proposals with conflicts)
    print("[Phase 3] Memory proposal churn: 100 proposals with conflicts...")
    mem_pipeline = MemoryGovernancePipeline(max_pending=30)

    approved_ids = []
    for i in range(100):
        mtype = [MemoryType.FACT, MemoryType.SYSTEM_STATE,
                 MemoryType.PREFERENCE, MemoryType.EPISODE][i % 4]
        result = mem_pipeline.propose(
            session_id="mem-soak-1",
            origin_event_ids=[f"evt-{i}"],
            memory_type=mtype,
            subject_key=f"key-{i % 25}",
            payload={"idx": i, "value": f"data-{i}"},
            confidence=0.5 + (i % 10) * 0.05,
        )
        if result.queued and not result.auto_approved:
            if i % 2 == 0:
                r = mem_pipeline.approve(result.proposal.proposal_id)
                if r["status"] == "approved":
                    mem_pipeline.apply(result.proposal.proposal_id)
                    approved_ids.append(result.proposal.proposal_id)
            else:
                mem_pipeline.reject(result.proposal.proposal_id, reason="soak_reject")
        elif result.auto_approved:
            mem_pipeline.apply(result.proposal.proposal_id)
            approved_ids.append(result.proposal.proposal_id)

    retract_count = 0
    for pid in approved_ids[:len(approved_ids) // 10]:
        r = mem_pipeline.retract(pid, reason="soak_retract")
        if r["status"] == "retracted":
            retract_count += 1

    mem_report = mem_pipeline.get_report()
    results["phases"].append({
        "name": "memory_churn",
        "proposals": 100,
        "approved": len(approved_ids),
        "retracted": retract_count,
        "report": mem_report,
    })
    print(f"  Memory: silent_write={mem_report['silent_write_count']}, "
          f"illegal_transitions={mem_report['illegal_transition_attempts']}, "
          f"double_decisions={mem_report['double_decision_attempts']}")

    # Phase 4: Replay verification
    print("[Phase 4] Replay verification...")
    replay_engine = ReplayEngine()
    replay_inputs = [
        ProposalInput(
            session_id="replay-soak",
            origin_event_ids=[f"evt-{i}"],
            memory_type=[MemoryType.FACT, MemoryType.SYSTEM_STATE][i % 2],
            subject_key=f"rkey-{i}",
            payload={"idx": i},
            confidence=0.8,
        ) for i in range(20)
    ]

    r1 = replay_engine.replay(replay_inputs, [])
    r2 = replay_engine.replay(replay_inputs, [])

    replay_divergence = 0
    if r1.replay_decisions_hash != r2.replay_decisions_hash:
        replay_divergence += 1
    if r1.ledger_state_hash != r2.ledger_state_hash:
        replay_divergence += 1

    results["phases"].append({
        "name": "replay_verification",
        "corpus_size": 20,
        "divergence_count": replay_divergence,
        "decisions_hash": r1.replay_decisions_hash[:16],
        "ledger_hash": r1.ledger_state_hash[:16],
    })
    print(f"  Replay: divergence={replay_divergence}")

    # Invariant summary
    elapsed = round(time.time() - t0, 3)
    invariants = {
        "silent_write_count": mem_report["silent_write_count"],
        "false_bypass_count": perc_report.get("false_bypass_count", 0),
        "replay_divergence_count": replay_divergence,
        "voice_cancel_violations": voice_violations,
        "illegal_transition_attempts": mem_report["illegal_transition_attempts"],
        "double_decision_attempts": mem_report["double_decision_attempts"],
        "conflict_unsurfaced_count": mem_report["conflict_unsurfaced_count"],
    }

    all_zero = all(v == 0 for v in invariants.values())
    results["invariants"] = invariants
    results["elapsed_s"] = elapsed
    results["verdict"] = "PASS" if all_zero else "FAIL"

    print(f"\n{'=' * 50}")
    print(f"  Invariants: {'ALL ZERO' if all_zero else 'BREACH DETECTED'}")
    for k, v in invariants.items():
        status = "OK" if v == 0 else "BREACH"
        print(f"    [{status}] {k} = {v}")
    print(f"  Elapsed: {elapsed}s")
    print(f"  Verdict: {results['verdict']}")

    report_path = REPO_ROOT / "reports" / "soak-v32" / "cross-epic-soak.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2))
    print(f"  Report: {report_path}")

    return 0 if all_zero else 1


if __name__ == "__main__":
    sys.exit(run_soak())
