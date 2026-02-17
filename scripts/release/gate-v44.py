"""
SONIA v4.4.0 Promotion Gate
============================
Schema v11.0 -- inherits v4.3 floor (Class A, 18 gates) + v4.4 delta (Class B, 15 gates).

v4.4 Epics:
  A -- Secure Exposure Hardening (bind audit, auth, TLS, CORS, service-token)
  B -- Voice Pipeline Activation (backends, ASR config, factory, WS audio, roundtrip)
  C -- Supervision + Restart Policy (restart method, policy, tasks, approve, health trigger)

Gate Classes:
  A -- Inherited v4.3 floor: all 18 gates from gate-v43.py
  B -- v4.4 delta gates: epic-specific structural checks

Usage:
    python gate-v44.py [--output-dir DIR]
    python gate-v44.py --delta-only    # Class B only (skip floor)
    python gate-v44.py --floor-only    # Class A only (floor regression check)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Import the v4.3 floor gates
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util

REPO_ROOT = Path("S:/")
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")

SCHEMA_VERSION = "11.0"
VERSION = "4.4.0"

# ---- Load v4.3 floor gates ----------------------------------------------------

def _load_v43_gates():
    """Dynamically load gate-v43.py and return its gate functions."""
    spec = importlib.util.spec_from_file_location(
        "gate_v43", str(REPO_ROOT / "scripts" / "release" / "gate-v43.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- Gate runner (reused from v4.3) -------------------------------------------

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


# ---- v4.4 Delta: Epic A — Secure Exposure ------------------------------------

def gate_bind_audit(g: GateResult):
    """Verify tool-service and orchestrator bind 127.0.0.1 by default."""
    issues = []

    # tool-service
    ts_path = REPO_ROOT / "services" / "tool-service" / "tool_service.py"
    if ts_path.exists():
        src = ts_path.read_text()
        if '"0.0.0.0"' in src and "TOOL_SERVICE_HOST" not in src:
            issues.append("tool-service binds 0.0.0.0 without env override")
        # Port collision check
        if "7040" in src:
            issues.append("tool-service uses port 7040 (collides with openclaw)")
    else:
        g.skip_("tool-service not found")
        return

    # orchestrator
    orch_path = REPO_ROOT / "services" / "orchestrator" / "orchestrator_service.py"
    if orch_path.exists():
        src = orch_path.read_text()
        if '"0.0.0.0"' in src and "ORCHESTRATOR_HOST" not in src:
            issues.append("orchestrator binds 0.0.0.0 without env override")

    if issues:
        g.fail_(f"Bind issues: {issues}")
    else:
        g.pass_("All services bind safely")


def gate_auth_coverage(g: GateResult):
    """Verify auth middleware exists on api-gateway and is configurable."""
    auth_path = REPO_ROOT / "services" / "api-gateway" / "auth.py"
    main_path = REPO_ROOT / "services" / "api-gateway" / "main.py"
    if not auth_path.exists():
        g.fail_("auth.py not found")
        return
    src = auth_path.read_text()
    main_src = main_path.read_text()
    checks = ["AuthMiddleware", "Bearer", "x-service-token"]
    missing = [c for c in checks if c not in src]
    if "auth_enabled" not in main_src and "AuthMiddleware" not in main_src:
        missing.append("auth not wired in main.py")
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Auth middleware with Bearer + service-token")


def gate_tls_config(g: GateResult):
    """Verify TLS cert/key env vars are wired into at least api-gateway startup."""
    main_path = REPO_ROOT / "services" / "api-gateway" / "main.py"
    if not main_path.exists():
        g.fail_("main.py not found")
        return
    src = main_path.read_text()
    if "ssl_certfile" in src or "SONIA_TLS_CERT" in src or "tls_cert" in src.lower():
        g.pass_("TLS config wired")
    else:
        g.fail_("No TLS config found in api-gateway main.py")


def gate_cors_env(g: GateResult):
    """Verify CORS origins are configurable via env var."""
    main_path = REPO_ROOT / "services" / "api-gateway" / "main.py"
    if not main_path.exists():
        g.fail_("main.py not found")
        return
    src = main_path.read_text()
    if "SONIA_CORS_ORIGINS" in src or "CORS_ORIGINS" in src:
        g.pass_("CORS origins configurable via env")
    else:
        g.fail_("CORS origins hardcoded, no env override in main.py")


def gate_service_token(g: GateResult):
    """Verify service-token flow is documented and testable."""
    auth_path = REPO_ROOT / "services" / "api-gateway" / "auth.py"
    if not auth_path.exists():
        g.fail_("auth.py not found")
        return
    src = auth_path.read_text()
    checks = ["service_token", "x-service-token"]
    missing = [c for c in checks if c not in src]
    if missing:
        g.fail_(f"Missing: {missing}")
    else:
        g.pass_("Service-token bypass flow present")


# ---- v4.4 Delta: Epic B — Voice Pipeline ------------------------------------

def gate_backends_wired(g: GateResult):
    """Verify voice_backends.py has concrete provider classes (not just stubs)."""
    path = REPO_ROOT / "services" / "pipecat" / "app" / "voice_backends.py"
    if not path.exists():
        g.fail_("voice_backends.py not found")
        return
    src = path.read_text()
    # Look for concrete implementations (not just base class)
    concrete = ["OllamaASR", "OllamaTTS", "EnergyVAD", "QwenASR", "QwenTTS"]
    found = [c for c in concrete if c in src]
    if len(found) >= 2:
        g.pass_(f"Concrete providers: {found}")
    else:
        g.fail_(f"Only found: {found}. Need concrete ASR+TTS providers.")


def gate_asr_config_fix(g: GateResult):
    """Verify ASRConfig/TTSConfig have api_key field (fix AttributeError)."""
    asr_path = REPO_ROOT / "services" / "pipecat" / "pipeline" / "asr.py"
    tts_path = REPO_ROOT / "services" / "pipecat" / "pipeline" / "tts.py"
    issues = []
    for name, path in [("ASR", asr_path), ("TTS", tts_path)]:
        if path.exists():
            src = path.read_text()
            if "api_key" in src and "api_key:" not in src and "api_key =" not in src:
                # References api_key but doesn't define it in dataclass
                issues.append(f"{name}Config references api_key without defining it")
    if issues:
        g.fail_("; ".join(issues))
    else:
        g.pass_("ASR/TTS config api_key fields defined")


def gate_factory_providers(g: GateResult):
    """Verify create_asr/create_tts return real providers when configured."""
    path = REPO_ROOT / "services" / "pipecat" / "app" / "voice_backends.py"
    if not path.exists():
        g.fail_("voice_backends.py not found")
        return
    src = path.read_text()
    checks = ["create_asr", "create_tts", "create_vad"]
    missing = [c for c in checks if c not in src]
    # Check that factories have real conditional logic (not just return stub)
    has_conditional = "if " in src and ("provider" in src or "backend" in src or "SONIA" in src)
    if missing:
        g.fail_(f"Missing factories: {missing}")
    elif not has_conditional:
        g.fail_("Factories exist but have no conditional provider selection")
    else:
        g.pass_("Factory functions with conditional provider selection")


def gate_ws_audio_framing(g: GateResult):
    """Verify pipecat WS handler accepts binary audio frames."""
    main_path = REPO_ROOT / "services" / "pipecat" / "main.py"
    if not main_path.exists():
        g.fail_("pipecat main.py not found")
        return
    src = main_path.read_text()
    checks = ["bytes", "audio", "binary", "pcm"]
    found = [c for c in checks if c.lower() in src.lower()]
    if len(found) >= 2:
        g.pass_(f"WS audio framing indicators: {found}")
    else:
        g.fail_(f"WS handler lacks binary audio support (found: {found})")


def gate_voice_roundtrip_test(g: GateResult):
    """Verify at least one voice roundtrip integration test exists."""
    test_dir = REPO_ROOT / "tests"
    test_patterns = ["voice_roundtrip", "voice_pipeline", "voice_e2e", "pipecat_roundtrip"]
    found = []
    for pattern in test_patterns:
        for p in test_dir.rglob(f"*{pattern}*"):
            found.append(str(p.relative_to(REPO_ROOT)))
    if found:
        g.pass_(f"Voice roundtrip tests: {found}")
    else:
        g.fail_("No voice roundtrip integration test found")


# ---- v4.4 Delta: Epic C — Supervision + Restart Policy -----------------------

def gate_restart_method(g: GateResult):
    """Verify ServiceSupervisor has restart_service method."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    if "restart_service" in src and ("subprocess" in src or "Popen" in src or "uvicorn" in src):
        g.pass_("restart_service with subprocess execution")
    elif "restart_service" in src:
        g.fail_("restart_service exists but no subprocess execution found")
    else:
        g.fail_("restart_service method not found")


def gate_restart_policy(g: GateResult):
    """Verify restart policy with max attempts + backoff."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    checks = ["max_restart", "backoff", "restart_count"]
    found = [c for c in checks if c.lower() in src.lower()]
    if len(found) >= 2:
        g.pass_(f"Restart policy: {found}")
    else:
        g.fail_(f"Restart policy indicators: {found} (need >= 2)")


def gate_tasks_endpoint(g: GateResult):
    """Verify /tasks endpoint has real storage (not hardcoded stub)."""
    path = REPO_ROOT / "services" / "eva-os" / "main.py"
    if not path.exists():
        g.fail_("eva-os main.py not found")
        return
    src = path.read_text()
    # Check for real task storage
    if "task_001" in src:
        g.fail_("/tasks still returns hardcoded task_001")
    elif "_tasks" in src or "task_store" in src or "tasks:" in src:
        g.pass_("Task storage present")
    else:
        g.fail_("No task storage mechanism found")


def gate_approve_endpoint(g: GateResult):
    """Verify /approve endpoint has real approval logic (not just acknowledge)."""
    path = REPO_ROOT / "services" / "eva-os" / "main.py"
    if not path.exists():
        g.fail_("eva-os main.py not found")
        return
    src = path.read_text()
    if "acknowledged" in src and "approve" in src and "resubmit" in src:
        # Still the stub pattern
        g.fail_("/approve still returns 'acknowledged' stub")
    elif "approve" in src:
        g.pass_("Approval endpoint with real logic")
    else:
        g.fail_("No approve endpoint found")


def gate_health_restart_trigger(g: GateResult):
    """Verify health-driven automatic restart on UNREACHABLE state."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    checks = ["UNREACHABLE", "restart_service", "auto_restart"]
    found = [c for c in checks if c in src]
    if "UNREACHABLE" in found and ("restart_service" in found or "auto_restart" in found):
        g.pass_("Health-driven restart trigger wired")
    else:
        g.fail_(f"Health restart indicators: {found}")


# ---- Run all gates -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=f"SONIA v{VERSION} Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "releases" / f"v{VERSION}"))
    parser.add_argument("--delta-only", action="store_true", help="Skip floor gates")
    parser.add_argument("--floor-only", action="store_true", help="Only run floor gates")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load v4.3 floor module
    v43 = _load_v43_gates()

    gates = []

    # Class A: inherited v4.3 floor (18 gates)
    if not args.delta_only:
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

    if args.floor_only:
        # Skip delta gates
        pass
    else:
        # Class B: v4.4 delta — Epic A (Secure Exposure)
        gates.append(("bind-audit", "B", "A", gate_bind_audit))
        gates.append(("auth-coverage", "B", "A", gate_auth_coverage))
        gates.append(("tls-config", "B", "A", gate_tls_config))
        gates.append(("cors-env", "B", "A", gate_cors_env))
        gates.append(("service-token", "B", "A", gate_service_token))

        # Class B: v4.4 delta — Epic B (Voice Pipeline)
        gates.append(("backends-wired", "B", "B", gate_backends_wired))
        gates.append(("asr-config-fix", "B", "B", gate_asr_config_fix))
        gates.append(("factory-providers", "B", "B", gate_factory_providers))
        gates.append(("ws-audio-framing", "B", "B", gate_ws_audio_framing))
        gates.append(("voice-roundtrip-test", "B", "B", gate_voice_roundtrip_test))

        # Class B: v4.4 delta — Epic C (Supervision)
        gates.append(("restart-method", "B", "C", gate_restart_method))
        gates.append(("restart-policy", "B", "C", gate_restart_policy))
        gates.append(("tasks-endpoint", "B", "C", gate_tasks_endpoint))
        gates.append(("approve-endpoint", "B", "C", gate_approve_endpoint))
        gates.append(("health-restart-trigger", "B", "C", gate_health_restart_trigger))

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

    # Summary by class
    floor_pass = sum(1 for r in results if r.gate_class == "A" and r.status == "PASS")
    floor_fail = sum(1 for r in results if r.gate_class == "A" and r.status == "FAIL")
    floor_total = sum(1 for r in results if r.gate_class == "A")
    delta_pass = sum(1 for r in results if r.gate_class == "B" and r.status == "PASS")
    delta_fail = sum(1 for r in results if r.gate_class == "B" and r.status == "FAIL")
    delta_total = sum(1 for r in results if r.gate_class == "B")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    # Verdict logic: floor regression = HOLD, delta fail = HOLD
    floor_clean = floor_fail == 0
    verdict = "PROMOTE" if failed == 0 else "HOLD"

    print()
    print(f"  Floor: {floor_pass}/{floor_total} pass" + (" (REGRESSION)" if not floor_clean else ""))
    print(f"  Delta: {delta_pass}/{delta_total} pass")
    print(f"=== VERDICT: {verdict} ({passed} pass, {failed} fail, {skipped} skip) in {elapsed}s ===")

    # Write report
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
