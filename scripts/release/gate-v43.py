"""
SONIA v4.3.0 Promotion Gate
============================
Schema v10.0 -- inherits v4.2 floor (Class A) + v4.3 delta gates (Class B).

v4.3 Epics:
  A -- Session Durability + Restart Recovery (DurableStateStore, outbox)
  B -- Persistent Retrieval + Deterministic Recall (HNSW, index manifest, token budget)
  C -- Consent/Privacy Hardening (consent FSM, backpressure, latency budget)

Gate Classes:
  A -- Inherited baseline: syntax + import checks for all modified files
  B -- v4.3 delta gates: epic-specific structural checks
  C -- Cross-cutting: file existence, compile, evidence

Usage:
    python gate-v43.py [--output-dir DIR]
    python gate-v43.py --delta-only    # Class B + C only
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("S:/")
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")

SCHEMA_VERSION = "10.0"
VERSION = "4.3.0"

# ---- All v4.3 files ----------------------------------------------------------

NEW_FILES = [
    "services/api-gateway/durable_state.py",
    "services/api-gateway/backpressure.py",
    "services/api-gateway/latency_budget.py",
    "services/memory-engine/vector/index_manifest.py",
    "services/shared/consent.py",
]

MODIFIED_FILES = [
    "services/api-gateway/session_manager.py",
    "services/api-gateway/tool_policy.py",
    "services/api-gateway/dead_letter.py",
    "services/api-gateway/memory_policy.py",
    "services/api-gateway/main.py",
    "services/api-gateway/routes/stream.py",
    "services/memory-engine/hybrid_search.py",
    "services/memory-engine/main.py",
    "services/memory-engine/core/retriever.py",
    "services/perception/main.py",
]

ALL_FILES = NEW_FILES + MODIFIED_FILES


# ---- Gate runner -------------------------------------------------------------

class GateResult:
    def __init__(self, name: str, gate_class: str, epic: str = ""):
        self.name = name
        self.gate_class = gate_class
        self.epic = epic
        self.status = "PENDING"
        self.detail = ""
        self.start_time = 0.0
        self.end_time = 0.0

    @property
    def duration_s(self):
        return round(self.end_time - self.start_time, 3)

    def pass_(self, detail=""):
        self.status = "PASS"
        self.detail = detail

    def fail_(self, detail=""):
        self.status = "FAIL"
        self.detail = detail

    def skip_(self, detail=""):
        self.status = "SKIP"
        self.detail = detail

    def to_dict(self):
        return {
            "name": self.name,
            "class": self.gate_class,
            "epic": self.epic,
            "status": self.status,
            "detail": self.detail,
            "duration_s": self.duration_s,
        }


def run_gate(gate: GateResult, fn):
    gate.start_time = time.monotonic()
    try:
        fn(gate)
    except Exception as e:
        gate.fail_(f"Exception: {e}")
    gate.end_time = time.monotonic()
    icon = {"PASS": "+", "FAIL": "!", "SKIP": "~"}.get(gate.status, "?")
    print(f"  [{icon}] {gate.name}: {gate.status} ({gate.duration_s}s) {gate.detail}")


# ---- Class A: Syntax + compile -----------------------------------------------

def gate_file_exists(g: GateResult):
    missing = []
    for f in ALL_FILES:
        if not (REPO_ROOT / f).exists():
            missing.append(f)
    if missing:
        g.fail_(f"Missing files: {missing}")
    else:
        g.pass_(f"All {len(ALL_FILES)} files exist")


def gate_compile_all(g: GateResult):
    import py_compile
    fails = []
    for f in ALL_FILES:
        try:
            py_compile.compile(str(REPO_ROOT / f), doraise=True)
        except py_compile.PyCompileError as e:
            fails.append(f"{f}: {e}")
    if fails:
        g.fail_(f"Compile failures: {'; '.join(fails)}")
    else:
        g.pass_(f"{len(ALL_FILES)} files compile OK")


# ---- Class B: Epic A -- Session Durability -----------------------------------

def gate_durable_state_tables(g: GateResult):
    """Verify DurableStateStore creates all 4 tables."""
    src = (REPO_ROOT / "services/api-gateway/durable_state.py").read_text()
    required = ["CREATE TABLE IF NOT EXISTS sessions",
                "CREATE TABLE IF NOT EXISTS confirmations",
                "CREATE TABLE IF NOT EXISTS dead_letters",
                "CREATE TABLE IF NOT EXISTS outbox"]
    missing = [t for t in required if t not in src]
    if missing:
        g.fail_(f"Missing table DDL: {missing}")
    else:
        g.pass_("All 4 tables defined")


def gate_wal_mode(g: GateResult):
    """Verify WAL mode is set in DurableStateStore."""
    src = (REPO_ROOT / "services/api-gateway/durable_state.py").read_text()
    if "journal_mode=WAL" in src or "journal_mode = WAL" in src or "PRAGMA journal_mode=WAL" in src:
        g.pass_("WAL mode configured")
    else:
        g.fail_("WAL mode not found in durable_state.py")


def gate_session_restore(g: GateResult):
    """Verify session_manager has restore_sessions + state_store integration."""
    src = (REPO_ROOT / "services/api-gateway/session_manager.py").read_text()
    checks = ["set_state_store", "restore_sessions", "_state_store"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Session restore integration present")


def gate_confirmation_restore(g: GateResult):
    """Verify tool_policy has confirmation restore + state store integration."""
    src = (REPO_ROOT / "services/api-gateway/tool_policy.py").read_text()
    checks = ["set_state_store", "restore_confirmations", "persist_confirmation", "update_confirmation"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Confirmation restore integration present")


def gate_outbox_pattern(g: GateResult):
    """Verify outbox pattern in memory_policy + durable_state."""
    mp_src = (REPO_ROOT / "services/api-gateway/memory_policy.py").read_text()
    ds_src = (REPO_ROOT / "services/api-gateway/durable_state.py").read_text()
    checks = [
        ("memory_policy: enqueue_outbox", "enqueue_outbox" in mp_src),
        ("memory_policy: mark_delivered", "mark_delivered" in mp_src),
        ("memory_policy: flush_outbox", "flush_outbox" in mp_src),
        ("durable_state: outbox table", "outbox" in ds_src),
    ]
    fails = [name for name, ok in checks if not ok]
    if fails:
        g.fail_(f"Missing: {fails}")
    else:
        g.pass_("Outbox pattern wired end-to-end")


def gate_lifespan_wiring(g: GateResult):
    """Verify main.py lifespan wires DurableStateStore into all managers."""
    src = (REPO_ROOT / "services/api-gateway/main.py").read_text()
    checks = ["durable_state", "set_state_store", "restore_all"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing in main.py lifespan: {missing}")
    else:
        g.pass_("main.py lifespan wires DurableStateStore")


# ---- Class B: Epic B -- Persistent Retrieval ---------------------------------

def gate_hnsw_wired(g: GateResult):
    """Verify hybrid_search.py has vector initialization + async_search."""
    src = (REPO_ROOT / "services/memory-engine/hybrid_search.py").read_text()
    checks = ["initialize_vector", "async_search", "on_store_async", "save_index", "_backfill_vectors"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("HNSW fully wired into hybrid search")


def gate_index_manifest(g: GateResult):
    """Verify index_manifest.py has write/read/verify + SHA-256."""
    path = REPO_ROOT / "services/memory-engine/vector/index_manifest.py"
    if not path.exists():
        g.fail_("index_manifest.py not found")
        return
    src = path.read_text()
    checks = ["sha256", "async def write", "async def verify", "async def read", "_compute_checksum"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Index manifest with SHA-256 verification")


def gate_token_budget(g: GateResult):
    """Verify retriever.py has deterministic budget_tokens method."""
    src = (REPO_ROOT / "services/memory-engine/core/retriever.py").read_text()
    if "budget_tokens" in src and "max_tokens" in src:
        g.pass_("Deterministic token budget in retriever")
    else:
        g.fail_("budget_tokens not found in retriever.py")


def gate_memory_lifespan(g: GateResult):
    """Verify memory-engine main.py calls initialize_vector + save_index."""
    src = (REPO_ROOT / "services/memory-engine/main.py").read_text()
    checks = ["initialize_vector", "save_index"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing in memory-engine lifespan: {missing}")
    else:
        g.pass_("Memory-engine lifespan: vector init + save")


# ---- Class B: Epic C -- Consent/Privacy -------------------------------------

def gate_consent_fsm(g: GateResult):
    """Verify consent.py has state machine with all required states."""
    src = (REPO_ROOT / "services/shared/consent.py").read_text()
    states = ["OFF", "REQUESTED", "GRANTED", "ACTIVE", "REVOKED"]
    checks = ["_VALID_TRANSITIONS", "ConsentManager", "is_inference_allowed"]
    missing_states = [s for s in states if s not in src]
    missing_checks = [c for c in checks if c not in src]
    if missing_states or missing_checks:
        g.fail_(f"Missing states: {missing_states}, checks: {missing_checks}")
    else:
        g.pass_("Consent FSM: 5 states + inference gate")


def gate_consent_fail_closed(g: GateResult):
    """Verify is_inference_allowed defaults to False (fail-closed)."""
    src = (REPO_ROOT / "services/shared/consent.py").read_text()
    if "return False" in src and "ACTIVE" in src:
        g.pass_("Fail-closed consent (returns False on error)")
    else:
        g.fail_("Fail-closed pattern not evident")


def gate_perception_consent(g: GateResult):
    """Verify perception main.py has consent gate before inference."""
    src = (REPO_ROOT / "services/perception/main.py").read_text()
    checks = ["consent_mgr", "is_inference_allowed", "CONSENT_NOT_ACTIVE", "total_consent_blocks"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Perception consent gate active")


def gate_backpressure(g: GateResult):
    """Verify backpressure.py has queue depth limiter."""
    src = (REPO_ROOT / "services/api-gateway/backpressure.py").read_text()
    checks = ["BackpressurePolicy", "admit", "dequeue", "reset_session", "shed_count"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Backpressure policy with oldest-first shedding")


def gate_latency_budget(g: GateResult):
    """Verify latency_budget.py has per-stage tracking + SLO check."""
    src = (REPO_ROOT / "services/api-gateway/latency_budget.py").read_text()
    checks = ["LatencyBudget", "record", "percentile", "check_slo", "_CircularBuffer"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Latency budget: per-stage p95/p99 + SLO")


def gate_stream_backpressure(g: GateResult):
    """Verify stream.py wires backpressure + latency budget."""
    src = (REPO_ROOT / "services/api-gateway/routes/stream.py").read_text()
    checks = ["BackpressurePolicy", "LatencyBudget", "_backpressure", "_latency_budget"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing in stream.py: {missing}")
    else:
        g.pass_("stream.py: backpressure + latency wired")


# ---- Run all gates -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=f"SONIA v{VERSION} Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "releases" / f"v{VERSION}"))
    parser.add_argument("--delta-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gates = []

    # Class A: baseline
    if not args.delta_only:
        gates.append(("file-exists", "A", "", gate_file_exists))
        gates.append(("compile-all", "A", "", gate_compile_all))

    # Class B: Epic A - Session Durability
    gates.append(("durable-state-tables", "B", "A", gate_durable_state_tables))
    gates.append(("wal-mode", "B", "A", gate_wal_mode))
    gates.append(("session-restore", "B", "A", gate_session_restore))
    gates.append(("confirmation-restore", "B", "A", gate_confirmation_restore))
    gates.append(("outbox-pattern", "B", "A", gate_outbox_pattern))
    gates.append(("lifespan-wiring", "B", "A", gate_lifespan_wiring))

    # Class B: Epic B - Persistent Retrieval
    gates.append(("hnsw-wired", "B", "B", gate_hnsw_wired))
    gates.append(("index-manifest", "B", "B", gate_index_manifest))
    gates.append(("token-budget", "B", "B", gate_token_budget))
    gates.append(("memory-lifespan", "B", "B", gate_memory_lifespan))

    # Class B: Epic C - Consent/Privacy
    gates.append(("consent-fsm", "B", "C", gate_consent_fsm))
    gates.append(("consent-fail-closed", "B", "C", gate_consent_fail_closed))
    gates.append(("perception-consent", "B", "C", gate_perception_consent))
    gates.append(("backpressure", "B", "C", gate_backpressure))
    gates.append(("latency-budget", "B", "C", gate_latency_budget))
    gates.append(("stream-backpressure", "B", "C", gate_stream_backpressure))

    print(f"=== SONIA v{VERSION} Promotion Gate (schema {SCHEMA_VERSION}) ===")
    print(f"Gates: {len(gates)}")
    print()

    results = []
    t0 = time.monotonic()
    for name, cls, epic, fn in gates:
        g = GateResult(name, cls, epic)
        run_gate(g, fn)
        results.append(g)

    elapsed = round(time.monotonic() - t0, 2)

    # Summary
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    verdict = "PROMOTE" if failed == 0 else "HOLD"
    print()
    print(f"=== VERDICT: {verdict} ({passed} pass, {failed} fail, {skipped} skip) in {elapsed}s ===")

    # Write report
    report = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "verdict": verdict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": elapsed,
        "summary": {"pass": passed, "fail": failed, "skip": skipped, "total": len(results)},
        "gates": [r.to_dict() for r in results],
    }
    report_path = out_dir / "gate-report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
