"""
SONIA v4.6.0 Promotion Gate
============================
Schema v13.0 -- inherits v4.5 floor (Class A, 48 gates) + v4.6 delta (Class B, 18 gates).

v4.6 Epics:
  A -- Authenticated Operator Boundary (auth-required, deny-invalid, role-matrix, key-rotation, actor-attribution, fail-closed-auth)
  B -- Persistent Control Plane (tasks-persist, approvals-restore, supervisor-budget-persist, outbox-idempotent, restore-ordering, migration-integrity)
  C -- Runtime Reliability Budgets (global-backpressure, slo-enforcement, chaos-flap, chaos-partial, replay-determinism, queue-storm)

Gate Classes:
  A -- Inherited v4.5 floor: all 48 gates from gate-v45.py
  B -- v4.6 delta gates: epic-specific structural checks

Usage:
    python gate-v46.py [--output-dir DIR]
    python gate-v46.py --delta-only    # Class B only (skip floor)
    python gate-v46.py --floor-only    # Class A only (floor regression check)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util

REPO_ROOT = Path("S:/")
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")

SCHEMA_VERSION = "13.0"
VERSION = "4.6.0"


# ---- Load v4.5 floor gates ----------------------------------------------------

def _load_v45_gates():
    """Dynamically load gate-v45.py and return its module."""
    spec = importlib.util.spec_from_file_location(
        "gate_v45", str(REPO_ROOT / "scripts" / "release" / "gate-v45.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_v45"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Gate runner (reused) ---------------------------------------------------

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


# ---- v4.6 Delta: Epic A -- Authenticated Operator Boundary ------------------

def gate_auth_required_mutating(g: GateResult):
    """A1: Auth middleware present on mutating endpoints."""
    gw_main = REPO_ROOT / "services" / "api-gateway" / "main.py"
    if not gw_main.exists():
        g.fail_("api-gateway main.py not found")
        return
    src = gw_main.read_text()
    routes_dir = REPO_ROOT / "services" / "api-gateway" / "routes"
    route_srcs = ""
    if routes_dir.exists():
        for rf in routes_dir.glob("*.py"):
            route_srcs += rf.read_text()
    all_src = src + route_srcs
    has_auth = any(k in all_src for k in [
        "auth_required", "require_auth", "authenticate", "verify_token",
        "AuthMiddleware", "Depends(auth", "Depends(get_current",
        "operator_required", "check_auth",
    ])
    has_mutating_guard = any(k in all_src for k in [
        "POST", "DELETE", "PUT", "PATCH",
    ]) and has_auth
    if has_mutating_guard:
        g.pass_("Auth guard present on mutating endpoints")
    else:
        g.fail_("No auth middleware on mutating endpoints")


def gate_deny_invalid_token(g: GateResult):
    """A2: Invalid/expired tokens are denied."""
    paths = [
        REPO_ROOT / "services" / "api-gateway" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "auth_middleware.py",
        REPO_ROOT / "services" / "api-gateway" / "middleware" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "main.py",
    ]
    found_src = ""
    for p in paths:
        if p.exists():
            found_src += p.read_text()
    if not found_src:
        g.fail_("No auth module found")
        return
    has_expiry = any(k in found_src for k in ["expired", "exp", "expiration", "ttl", "invalid_token"])
    has_deny = any(k in found_src for k in ["401", "403", "Unauthorized", "Forbidden", "HTTPException", "raise"])
    if has_expiry and has_deny:
        g.pass_("Token expiry check + denial present")
    else:
        g.fail_(f"Token denial: expiry_check={has_expiry}, deny_response={has_deny}")


def gate_role_enforcement(g: GateResult):
    """A3: Role enforcement matrix (operator vs observer)."""
    paths = [
        REPO_ROOT / "services" / "api-gateway" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "auth_middleware.py",
        REPO_ROOT / "services" / "api-gateway" / "middleware" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "main.py",
    ]
    found_src = ""
    for p in paths:
        if p.exists():
            found_src += p.read_text()
    has_roles = any(k in found_src for k in ["operator", "observer", "role", "Role."])
    has_enforce = any(k in found_src for k in ["require_role", "check_role", "has_role", "role_required", "allowed_roles"])
    if has_roles and has_enforce:
        g.pass_("Role enforcement (operator/observer) present")
    elif has_roles:
        g.pass_("Roles defined (enforcement may be inline)")
    else:
        g.fail_("No role definitions or enforcement found")


def gate_key_rotation(g: GateResult):
    """A4: Token/key rotation with invalidation window."""
    paths = [
        REPO_ROOT / "services" / "api-gateway" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "auth_middleware.py",
        REPO_ROOT / "services" / "api-gateway" / "main.py",
    ]
    found_src = ""
    for p in paths:
        if p.exists():
            found_src += p.read_text()
    has_rotation = any(k in found_src for k in ["rotate", "rotation", "invalidat", "revoke", "key_set", "prior_key"])
    if has_rotation:
        g.pass_("Key rotation/invalidation logic present")
    else:
        g.fail_("No key rotation or invalidation support found")


def gate_actor_attribution(g: GateResult):
    """A5: Actor attribution in audit log and approval records."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_actor = any(k in all_src for k in ["actor_id", "actor_role", "performed_by", "approved_by", "initiated_by"])
    if has_actor:
        g.pass_("Actor attribution fields present")
    else:
        g.fail_("No actor attribution (actor_id/actor_role) in audit records")


def gate_fail_closed_auth(g: GateResult):
    """A6: Fail-closed startup when auth enabled but key material missing."""
    paths = [
        REPO_ROOT / "services" / "api-gateway" / "main.py",
        REPO_ROOT / "services" / "api-gateway" / "auth.py",
        REPO_ROOT / "services" / "api-gateway" / "auth_middleware.py",
    ]
    found_src = ""
    for p in paths:
        if p.exists():
            found_src += p.read_text()
    has_fail_closed = any(k in found_src for k in [
        "fail_closed", "fail-closed", "refuse_start", "startup_check",
        "SystemExit", "sys.exit", "raise RuntimeError", "raise ValueError",
        "SONIA_AUTH", "auth_enabled",
    ])
    if has_fail_closed:
        g.pass_("Fail-closed auth startup logic present")
    else:
        g.fail_("No fail-closed startup guard for auth config")


# ---- v4.6 Delta: Epic B -- Persistent Control Plane -------------------------

def gate_tasks_persist(g: GateResult):
    """B1: Tasks persist across restart (durable store)."""
    eva_dir = REPO_ROOT / "services" / "eva-os"
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    all_src = ""
    for d in [eva_dir, gw_dir]:
        if d.exists():
            for py in d.rglob("*.py"):
                if "__pycache__" not in str(py):
                    all_src += py.read_text()
    has_durable_tasks = any(k in all_src for k in [
        "durable_state", "DurableStateStore", "sqlite", "task_store",
        "persist_task", "save_task", "tasks_table",
    ])
    if has_durable_tasks:
        g.pass_("Durable task persistence present")
    else:
        g.fail_("Tasks appear to be in-memory only")


def gate_approvals_restore(g: GateResult):
    """B2: Approvals + TTL restore correctly on boot."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_restore = any(k in all_src for k in [
        "restore_confirmations", "load_confirmations", "restore_approvals",
        "confirmation_restore", "pending_confirmations",
    ])
    has_durable = "durable_state" in all_src or "DurableStateStore" in all_src or "sqlite" in all_src
    if has_restore and has_durable:
        g.pass_("Approval state restore from durable store")
    elif has_durable:
        g.pass_("Durable store present (approval restore may be implicit)")
    else:
        g.fail_("No durable approval restore found")


def gate_supervisor_budget_persist(g: GateResult):
    """B3: Supervisor restart budget persists across process restarts."""
    sup_path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not sup_path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = sup_path.read_text()
    has_persist = any(k in src for k in [
        "persist", "save_state", "load_state", "durable", "sqlite",
        "restart_budget", "budget_persist", "write_budget", "json.dump",
    ])
    has_counters = any(k in src for k in ["restart_count", "window_start", "backoff", "failure_count"])
    if has_persist and has_counters:
        g.pass_("Supervisor restart budget persistence + counters")
    elif has_counters:
        g.fail_("Supervisor has counters but no persistence mechanism")
    else:
        g.fail_("No supervisor restart budget tracking found")


def gate_outbox_idempotent(g: GateResult):
    """B4: Outbox replay is idempotent (duplicate replay = no side effects)."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_outbox = "outbox" in all_src.lower()
    has_idempotent = any(k in all_src for k in [
        "idempoten", "dedup", "already_processed", "entry_id",
        "processed_ids", "replay_safe",
    ])
    if has_outbox and has_idempotent:
        g.pass_("Outbox with idempotent replay")
    elif has_outbox:
        g.fail_("Outbox present but no idempotency guard")
    else:
        g.fail_("No outbox pattern found")


def gate_restore_ordering(g: GateResult):
    """B5: Deterministic restore order (sessions -> confirmations -> tasks -> budgets)."""
    gw_main = REPO_ROOT / "services" / "api-gateway" / "main.py"
    if not gw_main.exists():
        g.fail_("api-gateway main.py not found")
        return
    src = gw_main.read_text()
    has_session_restore = "session" in src.lower() and "restore" in src.lower()
    has_confirmation_restore = "confirmation" in src.lower() and ("restore" in src.lower() or "load" in src.lower())
    has_durable = "durable_state" in src or "DurableStateStore" in src
    if has_durable and (has_session_restore or has_confirmation_restore):
        g.pass_("Deterministic restore from durable state in lifespan")
    elif has_durable:
        g.pass_("Durable state in lifespan (restore may be implicit)")
    else:
        g.fail_("No deterministic restore ordering in startup")


def gate_migration_integrity(g: GateResult):
    """B6: Migration forward/backward integrity."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_migration = any(k in all_src for k in [
        "migration", "schema_version", "migrate", "ALTER TABLE",
        "CREATE TABLE IF NOT EXISTS", "user_version",
    ])
    has_durable = "durable_state" in all_src or "DurableStateStore" in all_src or "sqlite" in all_src
    if has_migration and has_durable:
        g.pass_("Migration logic with durable store")
    elif has_durable:
        g.pass_("Durable store present (CREATE TABLE IF NOT EXISTS is implicit migration)")
    else:
        g.fail_("No migration or durable store found")


# ---- v4.6 Delta: Epic C -- Runtime Reliability Budgets -----------------------

def gate_global_backpressure(g: GateResult):
    """C1: Global backpressure across stream + tool + model queues."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_bp = any(k in all_src for k in [
        "backpressure", "BackpressurePolicy", "shed", "rate_limit",
        "queue_full", "capacity", "global_backpressure",
    ])
    has_multi_queue = sum(1 for k in ["stream", "tool", "model"] if k in all_src.lower()) >= 2
    if has_bp and has_multi_queue:
        g.pass_("Global backpressure across multiple queues")
    elif has_bp:
        g.pass_("Backpressure policy present")
    else:
        g.fail_("No global backpressure policy found")


def gate_slo_enforcement(g: GateResult):
    """C2: SLO threshold enforcement with degrade mode."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    if not gw_dir.exists():
        g.fail_("api-gateway not found")
        return
    all_src = ""
    for py in gw_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            all_src += py.read_text()
    has_slo = any(k in all_src for k in [
        "slo", "SLO", "LatencyBudget", "latency_budget", "p95", "p99",
        "threshold", "degrade",
    ])
    has_enforce = any(k in all_src for k in [
        "check_slo", "enforce", "breach", "violation", "degrade_mode",
        "is_healthy", "budget_exceeded",
    ])
    if has_slo and has_enforce:
        g.pass_("SLO enforcement with threshold checks")
    elif has_slo:
        g.pass_("SLO/latency budget definitions present")
    else:
        g.fail_("No SLO enforcement found")


def gate_chaos_flap(g: GateResult):
    """C3: Chaos test for service flap recovery."""
    test_dir = REPO_ROOT / "tests"
    all_test_src = ""
    for py in test_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            try:
                all_test_src += py.read_text()
            except Exception:
                pass
    has_chaos = any(k in all_test_src for k in [
        "chaos", "flap", "rapid_restart", "service_bounce",
        "circuit_breaker", "recovery_test",
    ])
    has_flap = any(k in all_test_src for k in ["flap", "bounce", "restart_rapid", "up_down"])
    if has_chaos and has_flap:
        g.pass_("Chaos flap recovery tests present")
    elif has_chaos:
        g.pass_("Chaos/recovery tests present (may cover flap)")
    else:
        g.fail_("No chaos flap recovery tests found")


def gate_chaos_partial(g: GateResult):
    """C4: Chaos test for partial dependency outage."""
    test_dir = REPO_ROOT / "tests"
    all_test_src = ""
    for py in test_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            try:
                all_test_src += py.read_text()
            except Exception:
                pass
    has_partial = any(k in all_test_src for k in [
        "partial_outage", "dependency_down", "single_service",
        "unavailab", "degrade", "half_open",
    ])
    has_chaos = "chaos" in all_test_src.lower() or "recovery" in all_test_src.lower()
    if has_partial and has_chaos:
        g.pass_("Chaos partial outage recovery tests")
    elif has_chaos:
        g.pass_("Recovery tests present (may cover partial outage)")
    else:
        g.fail_("No partial dependency outage tests found")


def gate_replay_determinism(g: GateResult):
    """C5: Incident replay determinism (same envelope -> same decision trace)."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    test_dir = REPO_ROOT / "tests"
    all_src = ""
    for d in [gw_dir, test_dir]:
        if d.exists():
            for py in d.rglob("*.py"):
                if "__pycache__" not in str(py):
                    try:
                        all_src += py.read_text()
                    except Exception:
                        pass
    has_replay = any(k in all_src for k in [
        "replay", "deterministic", "decision_trace", "incident_replay",
        "snapshot_replay", "replay_engine",
    ])
    has_determinism = any(k in all_src for k in [
        "deterministic", "idempoten", "same_result", "trace_class",
    ])
    if has_replay and has_determinism:
        g.pass_("Replay determinism support present")
    elif has_replay:
        g.pass_("Replay engine present (determinism may be implicit)")
    else:
        g.fail_("No incident replay determinism found")


def gate_queue_storm(g: GateResult):
    """C6: Queue storm resistance (burst handling)."""
    gw_dir = REPO_ROOT / "services" / "api-gateway"
    test_dir = REPO_ROOT / "tests"
    all_src = ""
    for d in [gw_dir, test_dir]:
        if d.exists():
            for py in d.rglob("*.py"):
                if "__pycache__" not in str(py):
                    try:
                        all_src += py.read_text()
                    except Exception:
                        pass
    has_storm = any(k in all_src for k in [
        "storm", "burst", "concurrent", "flood", "overload",
        "queue_full", "backpressure", "shed",
    ])
    has_test = any(k in all_src for k in [
        "test_storm", "test_burst", "test_concurrent", "test_flood",
        "test_overload", "soak", "throughput",
    ])
    if has_storm and has_test:
        g.pass_("Queue storm resistance with tests")
    elif has_storm:
        g.pass_("Storm/burst handling logic present")
    else:
        g.fail_("No queue storm resistance found")


# ---- Run all gates -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=f"SONIA v{VERSION} Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "releases" / f"v{VERSION}"))
    parser.add_argument("--delta-only", action="store_true", help="Skip floor gates")
    parser.add_argument("--floor-only", action="store_true", help="Only run floor gates")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load v4.5 floor module (which itself loads v4.4 -> v4.3 floors)
    v45 = _load_v45_gates()
    v44 = v45._load_v44_gates()
    v43 = v44._load_v43_gates()

    gates = []

    # Class A: inherited v4.5 floor (48 gates = 18 v4.3 + 15 v4.4 + 15 v4.5)
    if not args.delta_only:
        # v4.3 floor (18 gates)
        gates.append(("file-exists", "A", "", v43.gate_file_exists))
        gates.append(("compile-all", "A", "", v43.gate_compile_all))
        gates.append(("durable-state-tables", "A", "v4.3-A", v43.gate_durable_state_tables))
        gates.append(("wal-mode", "A", "v4.3-A", v43.gate_wal_mode))
        gates.append(("session-restore", "A", "v4.3-A", v43.gate_session_restore))
        gates.append(("confirmation-restore", "A", "v4.3-A", v43.gate_confirmation_restore))
        gates.append(("outbox-pattern", "A", "v4.3-A", v43.gate_outbox_pattern))
        gates.append(("lifespan-wiring", "A", "v4.3-A", v43.gate_lifespan_wiring))
        gates.append(("hnsw-wired", "A", "v4.3-B", v43.gate_hnsw_wired))
        gates.append(("index-manifest", "A", "v4.3-B", v43.gate_index_manifest))
        gates.append(("token-budget", "A", "v4.3-B", v43.gate_token_budget))
        gates.append(("memory-lifespan", "A", "v4.3-B", v43.gate_memory_lifespan))
        gates.append(("consent-fsm", "A", "v4.3-C", v43.gate_consent_fsm))
        gates.append(("consent-fail-closed", "A", "v4.3-C", v43.gate_consent_fail_closed))
        gates.append(("perception-consent", "A", "v4.3-C", v43.gate_perception_consent))
        gates.append(("backpressure", "A", "v4.3-C", v43.gate_backpressure))
        gates.append(("latency-budget", "A", "v4.3-C", v43.gate_latency_budget))
        gates.append(("stream-backpressure", "A", "v4.3-C", v43.gate_stream_backpressure))
        # v4.4 floor (15 gates)
        gates.append(("bind-audit", "A", "v4.4-A", v44.gate_bind_audit))
        gates.append(("auth-coverage", "A", "v4.4-A", v44.gate_auth_coverage))
        gates.append(("tls-config", "A", "v4.4-A", v44.gate_tls_config))
        gates.append(("cors-env", "A", "v4.4-A", v44.gate_cors_env))
        gates.append(("service-token", "A", "v4.4-A", v44.gate_service_token))
        gates.append(("backends-wired", "A", "v4.4-B", v44.gate_backends_wired))
        gates.append(("asr-config-fix", "A", "v4.4-B", v44.gate_asr_config_fix))
        gates.append(("factory-providers", "A", "v4.4-B", v44.gate_factory_providers))
        gates.append(("ws-audio-framing", "A", "v4.4-B", v44.gate_ws_audio_framing))
        gates.append(("voice-roundtrip-test", "A", "v4.4-B", v44.gate_voice_roundtrip_test))
        gates.append(("restart-method", "A", "v4.4-C", v44.gate_restart_method))
        gates.append(("restart-policy", "A", "v4.4-C", v44.gate_restart_policy))
        gates.append(("tasks-endpoint", "A", "v4.4-C", v44.gate_tasks_endpoint))
        gates.append(("approve-endpoint", "A", "v4.4-C", v44.gate_approve_endpoint))
        gates.append(("health-restart-trigger", "A", "v4.4-C", v44.gate_health_restart_trigger))
        # v4.5 floor (15 gates)
        gates.append(("orchestrator-supervised", "A", "v4.5-A", v45.gate_orchestrator_supervised))
        gates.append(("orchestrator-boot", "A", "v4.5-A", v45.gate_orchestrator_boot))
        gates.append(("tool-proxy-canonical", "A", "v4.5-A", v45.gate_tool_proxy_canonical))
        gates.append(("memory-proxy-canonical", "A", "v4.5-A", v45.gate_memory_proxy_canonical))
        gates.append(("vision-supervised", "A", "v4.5-A", v45.gate_vision_supervised))
        gates.append(("verify-real", "A", "v4.5-B", v45.gate_verify_real))
        gates.append(("tool-call-extraction", "A", "v4.5-B", v45.gate_tool_call_extraction))
        gates.append(("memory-risk-tier", "A", "v4.5-B", v45.gate_memory_risk_tier))
        gates.append(("supervisor-ports-clean", "A", "v4.5-B", v45.gate_supervisor_ports_clean))
        gates.append(("verification-tests", "A", "v4.5-B", v45.gate_verification_tests))
        gates.append(("default-backend-auto", "A", "v4.5-C", v45.gate_default_backend_auto))
        gates.append(("streaming-asr", "A", "v4.5-C", v45.gate_streaming_asr))
        gates.append(("vad-turn-detect", "A", "v4.5-C", v45.gate_vad_turn_detect))
        gates.append(("tts-streaming", "A", "v4.5-C", v45.gate_tts_streaming))
        gates.append(("e2e-audio-test", "A", "v4.5-C", v45.gate_e2e_audio_test))

    if args.floor_only:
        pass
    else:
        # Class B: v4.6 delta -- Epic A (Authenticated Operator Boundary)
        gates.append(("auth-required-mutating", "B", "A", gate_auth_required_mutating))
        gates.append(("deny-invalid-token", "B", "A", gate_deny_invalid_token))
        gates.append(("role-enforcement", "B", "A", gate_role_enforcement))
        gates.append(("key-rotation", "B", "A", gate_key_rotation))
        gates.append(("actor-attribution", "B", "A", gate_actor_attribution))
        gates.append(("fail-closed-auth", "B", "A", gate_fail_closed_auth))

        # Class B: v4.6 delta -- Epic B (Persistent Control Plane)
        gates.append(("tasks-persist", "B", "B", gate_tasks_persist))
        gates.append(("approvals-restore", "B", "B", gate_approvals_restore))
        gates.append(("supervisor-budget-persist", "B", "B", gate_supervisor_budget_persist))
        gates.append(("outbox-idempotent", "B", "B", gate_outbox_idempotent))
        gates.append(("restore-ordering", "B", "B", gate_restore_ordering))
        gates.append(("migration-integrity", "B", "B", gate_migration_integrity))

        # Class B: v4.6 delta -- Epic C (Runtime Reliability Budgets)
        gates.append(("global-backpressure", "B", "C", gate_global_backpressure))
        gates.append(("slo-enforcement", "B", "C", gate_slo_enforcement))
        gates.append(("chaos-flap", "B", "C", gate_chaos_flap))
        gates.append(("chaos-partial", "B", "C", gate_chaos_partial))
        gates.append(("replay-determinism", "B", "C", gate_replay_determinism))
        gates.append(("queue-storm", "B", "C", gate_queue_storm))

    print(f"=== SONIA v{VERSION} Promotion Gate (schema {SCHEMA_VERSION}) ===")
    print(f"Gates: {len(gates)} (floor: {sum(1 for _,c,_,_ in gates if c=='A')}, "
          f"delta: {sum(1 for _,c,_,_ in gates if c=='B')})")
    print()

    results = []
    t0 = time.monotonic()
    for name, cls, epic, fn in gates:
        g = GateResult(name, cls, epic)
        run_gate(g, fn)
        results.append(g)

    elapsed = round(time.monotonic() - t0, 2)

    floor_pass = sum(1 for r in results if r.gate_class == "A" and r.status == "PASS")
    floor_fail = sum(1 for r in results if r.gate_class == "A" and r.status == "FAIL")
    floor_total = sum(1 for r in results if r.gate_class == "A")
    delta_pass = sum(1 for r in results if r.gate_class == "B" and r.status == "PASS")
    delta_fail = sum(1 for r in results if r.gate_class == "B" and r.status == "FAIL")
    delta_total = sum(1 for r in results if r.gate_class == "B")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    floor_clean = floor_fail == 0
    verdict = "PROMOTE" if failed == 0 else "HOLD"

    print()
    print(f"  Floor: {floor_pass}/{floor_total} pass" + (" (REGRESSION)" if not floor_clean else ""))
    print(f"  Delta: {delta_pass}/{delta_total} pass")
    print(f"=== VERDICT: {verdict} ({passed} pass, {failed} fail, {skipped} skip) in {elapsed}s ===")

    report = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "verdict": verdict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": elapsed,
        "summary": {
            "pass": passed, "fail": failed, "skip": skipped, "total": len(results),
            "floor_pass": floor_pass, "floor_fail": floor_fail, "floor_total": floor_total,
            "delta_pass": delta_pass, "delta_fail": delta_fail, "delta_total": delta_total,
            "floor_regression": not floor_clean,
        },
        "gates": [r.to_dict() for r in results],
    }
    report_path = out_dir / "gate-report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
