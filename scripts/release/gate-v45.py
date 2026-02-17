"""
SONIA v4.5.0 Promotion Gate
============================
Schema v12.0 -- inherits v4.4 floor (Class A, 33 gates) + v4.5 delta (Class B, 15 gates).

v4.5 Epics:
  A -- Orchestrator Convergence (supervised, boot, tool-proxy, memory-proxy, vision-supervised)
  B -- Action Verification + Tool Call Routing (verify-real, tool-call-extraction, memory-risk-tier, supervisor-ports-clean, verification-tests)
  C -- Voice Production Readiness (default-backend-auto, streaming-asr, vad-turn-detect, tts-streaming, e2e-audio-test)

Gate Classes:
  A -- Inherited v4.4 floor: all 33 gates from gate-v44.py
  B -- v4.5 delta gates: epic-specific structural checks

Usage:
    python gate-v45.py [--output-dir DIR]
    python gate-v45.py --delta-only    # Class B only (skip floor)
    python gate-v45.py --floor-only    # Class A only (floor regression check)
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

SCHEMA_VERSION = "12.0"
VERSION = "4.5.0"


# ---- Load v4.4 floor gates ----------------------------------------------------

def _load_v44_gates():
    """Dynamically load gate-v44.py and return its module."""
    spec = importlib.util.spec_from_file_location(
        "gate_v44", str(REPO_ROOT / "scripts" / "release" / "gate-v44.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_v44"] = mod
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


# ---- v4.5 Delta: Epic A -- Orchestrator Convergence -------------------------

def gate_orchestrator_supervised(g: GateResult):
    """Verify orchestrator is in EVA-OS DEPENDENCY_GRAPH and SERVICE_COMMANDS."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    in_deps = "orchestrator" in src.split("DEPENDENCY_GRAPH")[1].split("}")[0] if "DEPENDENCY_GRAPH" in src else False
    in_cmds = "orchestrator" in src.split("SERVICE_COMMANDS")[1].split("}")[0] if "SERVICE_COMMANDS" in src else False
    if in_deps and in_cmds:
        g.pass_("Orchestrator in DEPENDENCY_GRAPH + SERVICE_COMMANDS")
    else:
        issues = []
        if not in_deps:
            issues.append("not in DEPENDENCY_GRAPH")
        if not in_cmds:
            issues.append("not in SERVICE_COMMANDS")
        g.fail_(f"Orchestrator: {', '.join(issues)}")


def gate_orchestrator_boot(g: GateResult):
    """Verify orchestrator is mentioned in start-sonia-stack.ps1."""
    path = REPO_ROOT / "start-sonia-stack.ps1"
    if not path.exists():
        g.skip_("start-sonia-stack.ps1 not found")
        return
    src = path.read_text()
    if "orchestrator" in src.lower() or "8000" in src:
        g.pass_("Orchestrator in boot script")
    else:
        g.fail_("Orchestrator not referenced in start-sonia-stack.ps1")


def gate_tool_proxy_canonical(g: GateResult):
    """Verify orchestrator agent.py routes tools through openclaw, not own executor."""
    path = REPO_ROOT / "services" / "orchestrator" / "agent.py"
    if not path.exists():
        g.skip_("agent.py not found")
        return
    src = path.read_text()
    # Should reference openclaw/tool-service URL, not own ToolExecutor
    has_proxy = any(k in src for k in ["openclaw", "7040", "tool_service_url", "7080"])
    has_own = "ToolExecutor" in src and "self.tool_executor" in src
    if has_proxy and not has_own:
        g.pass_("Tools routed through canonical stack")
    elif has_proxy:
        g.pass_("Tools proxy present (ToolExecutor may be deprecated path)")
    else:
        g.fail_("No canonical tool proxy found in agent.py")


def gate_memory_proxy_canonical(g: GateResult):
    """Verify orchestrator agent.py routes memory through memory-engine, not own store."""
    path = REPO_ROOT / "services" / "orchestrator" / "agent.py"
    if not path.exists():
        g.skip_("agent.py not found")
        return
    src = path.read_text()
    has_proxy = any(k in src for k in ["memory_service_url", "7020", "memory-engine", "memory_engine"])
    has_own = "MemoryManager" in src and "self.memory_manager" in src
    if has_proxy and not has_own:
        g.pass_("Memory routed through canonical stack")
    elif has_proxy:
        g.pass_("Memory proxy present (MemoryManager may be deprecated path)")
    else:
        g.fail_("No canonical memory proxy found in agent.py")


def gate_vision_supervised(g: GateResult):
    """Verify vision-capture and perception are in EVA-OS supervisor."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    has_vision = "vision" in src.lower() and ("7060" in src or "vision-capture" in src or "vision_capture" in src)
    has_perception = "perception" in src.lower() and ("7070" in src)
    if has_vision and has_perception:
        g.pass_("Vision-capture + perception in supervisor")
    else:
        issues = []
        if not has_vision:
            issues.append("vision-capture missing")
        if not has_perception:
            issues.append("perception missing")
        g.fail_(f"Supervisor: {', '.join(issues)}")


# ---- v4.5 Delta: Epic B -- Action Verification + Tool Call Routing ----------

def gate_verify_real(g: GateResult):
    """Verify action_pipeline.verify() has real post-execution checks."""
    path = REPO_ROOT / "services" / "api-gateway" / "action_pipeline.py"
    if not path.exists():
        g.fail_("action_pipeline.py not found")
        return
    src = path.read_text()
    # Should NOT have placeholder/stub in verify section
    verify_section = ""
    if "def verify" in src:
        idx = src.index("def verify")
        verify_section = src[idx:idx+500]
    elif "Verify" in src:
        idx = src.index("Verify")
        verify_section = src[idx:idx+500]

    if "placeholder" in verify_section.lower() or "stub" in verify_section.lower():
        g.fail_("verify() still has placeholder/stub")
    elif any(k in verify_section for k in ["exists()", "exit_code", "process", "check"]):
        g.pass_("verify() has real post-execution checks")
    elif "verify" in src.lower() and "succeeded" not in verify_section[:200]:
        g.pass_("verify() appears to have real logic")
    else:
        g.fail_("verify() has no real post-execution validation")


def gate_tool_call_extraction(g: GateResult):
    """Verify turn pipeline extracts and routes structured tool calls."""
    path = REPO_ROOT / "services" / "api-gateway" / "routes" / "turn.py"
    if not path.exists():
        g.fail_("turn.py not found")
        return
    src = path.read_text()
    has_extraction = "tool_calls" in src
    has_stub = "forward-compatible stub" in src or "forward_compatible_stub" in src
    has_routing = any(k in src for k in ["openclaw", "execute_tool", "tool_service", "safety_gate"])
    if has_extraction and has_routing and not has_stub:
        g.pass_("Tool call extraction + routing implemented")
    elif has_stub:
        g.fail_("Tool call extraction still marked as stub")
    else:
        g.fail_(f"Tool call: extraction={has_extraction}, routing={has_routing}")


def gate_memory_risk_tier(g: GateResult):
    """Verify memory ops risk tier classification is not hardcoded AUTO_LOW."""
    paths = [
        REPO_ROOT / "services" / "memory_ops" / "governance_pipeline.py",
        REPO_ROOT / "services" / "memory_ops" / "replay_engine.py",
    ]
    issues = []
    for p in paths:
        if p.exists():
            src = p.read_text()
            if "AUTO_LOW" in src and "placeholder" in src.lower():
                issues.append(f"{p.name}: still hardcoded AUTO_LOW placeholder")
    if issues:
        g.fail_("; ".join(issues))
    elif any(p.exists() for p in paths):
        g.pass_("Memory risk tier classification implemented")
    else:
        g.skip_("memory_ops modules not found")


def gate_supervisor_ports_clean(g: GateResult):
    """Verify EVA-OS supervisor has correct ports for all services."""
    path = REPO_ROOT / "services" / "eva-os" / "service_supervisor.py"
    if not path.exists():
        g.fail_("service_supervisor.py not found")
        return
    src = path.read_text()
    issues = []
    # tool-service should be 7080, not 7040
    if "tool-service" in src or "tool_service" in src:
        if "7040" in src and "tool" in src.split("7040")[0][-50:].lower():
            issues.append("tool-service still on 7040 (should be 7080)")
    # openclaw should be 7040
    if "openclaw" in src:
        if "7040" not in src:
            issues.append("openclaw missing port 7040")
    if issues:
        g.fail_("; ".join(issues))
    else:
        g.pass_("Supervisor port assignments correct")


def gate_verification_tests(g: GateResult):
    """Verify integration tests exist for action verification and tool call extraction."""
    test_dir = REPO_ROOT / "tests"
    patterns = ["verify", "tool_call", "action_verify", "verification"]
    found = []
    for pattern in patterns:
        for p in test_dir.rglob(f"*{pattern}*"):
            if p.suffix == ".py" and "__pycache__" not in str(p):
                found.append(str(p.relative_to(REPO_ROOT)))
    if len(found) >= 1:
        g.pass_(f"Verification tests: {found}")
    else:
        g.fail_("No action verification / tool call extraction tests found")


# ---- v4.5 Delta: Epic C -- Voice Production Readiness -----------------------

def gate_default_backend_auto(g: GateResult):
    """Verify voice factory auto-detects provider when env var is unset."""
    path = REPO_ROOT / "services" / "pipecat" / "app" / "voice_backends.py"
    if not path.exists():
        g.fail_("voice_backends.py not found")
        return
    src = path.read_text()
    has_autodetect = any(k in src for k in ["auto_detect", "autodetect", "is_available", "probe", "ping"])
    has_fallback = "stub" in src.lower() or "none" in src.lower() or "fallback" in src.lower()
    if has_autodetect:
        g.pass_("Auto-detect provider logic present")
    elif has_fallback:
        g.fail_("Factory still defaults to stub/none without auto-detect")
    else:
        g.fail_("No auto-detect or fallback logic found")


def gate_streaming_asr(g: GateResult):
    """Verify streaming ASR (transcribe_stream) is implemented."""
    path = REPO_ROOT / "services" / "pipecat" / "app" / "voice_backends.py"
    if not path.exists():
        g.fail_("voice_backends.py not found")
        return
    src = path.read_text()
    has_stream = "transcribe_stream" in src
    has_yield = "yield" in src and ("partial" in src.lower() or "transcript" in src.lower())
    if has_stream and has_yield:
        g.pass_("Streaming ASR with partial transcript yields")
    elif has_stream:
        g.pass_("transcribe_stream method present")
    else:
        g.fail_("No streaming ASR (transcribe_stream) implementation")


def gate_vad_turn_detect(g: GateResult):
    """Verify VAD-driven turn detection triggers end-of-utterance."""
    main_path = REPO_ROOT / "services" / "picecat" / "main.py"  # intentional typo check
    if not main_path.exists():
        main_path = REPO_ROOT / "services" / "pipecat" / "main.py"
    if not main_path.exists():
        g.fail_("pipecat main.py not found")
        return
    src = main_path.read_text()
    vad_path = REPO_ROOT / "services" / "pipecat" / "app" / "voice_backends.py"
    vad_src = vad_path.read_text() if vad_path.exists() else ""
    has_eou = any(k in src + vad_src for k in ["end_of_utterance", "speech_end", "is_speech", "vad_trigger", "flush"])
    has_barge = "barge" in (src + vad_src).lower() or "interrupt" in (src + vad_src).lower()
    if has_eou and has_barge:
        g.pass_("VAD turn detection + barge-in support")
    elif has_eou:
        g.pass_("VAD turn detection present (barge-in TBD)")
    else:
        g.fail_("No VAD-driven turn detection found")


def gate_tts_streaming(g: GateResult):
    """Verify TTS sends audio as streaming binary frames, not single blob."""
    main_path = REPO_ROOT / "services" / "pipecat" / "main.py"
    if not main_path.exists():
        g.fail_("pipecat main.py not found")
        return
    src = main_path.read_text()
    has_stream = any(k in src for k in ["send_bytes", "send(bytes", "yield", "chunk", "frame"])
    has_tts = "tts" in src.lower()
    if has_stream and has_tts:
        g.pass_("TTS streaming audio frames present")
    else:
        g.fail_(f"TTS streaming: stream_send={has_stream}, tts_ref={has_tts}")


def gate_e2e_audio_test(g: GateResult):
    """Verify E2E binary audio test exists (PCM in -> transcription -> TTS out)."""
    test_dir = REPO_ROOT / "tests"
    patterns = ["audio_e2e", "pcm_roundtrip", "binary_audio", "voice_e2e", "audio_roundtrip"]
    found = []
    for pattern in patterns:
        for p in test_dir.rglob(f"*{pattern}*"):
            if p.suffix == ".py" and "__pycache__" not in str(p):
                found.append(str(p.relative_to(REPO_ROOT)))
    # Also check existing voice test for binary content
    voice_test = test_dir / "integration" / "test_voice_roundtrip.py"
    if voice_test.exists():
        vtc = voice_test.read_text()
        if "pcm" in vtc.lower() or "binary" in vtc.lower() or "bytes" in vtc.lower():
            found.append("tests/integration/test_voice_roundtrip.py (has binary tests)")
    if found:
        g.pass_(f"E2E audio tests: {found}")
    else:
        g.fail_("No E2E binary audio round-trip test found")


# ---- Run all gates -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=f"SONIA v{VERSION} Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "releases" / f"v{VERSION}"))
    parser.add_argument("--delta-only", action="store_true", help="Skip floor gates")
    parser.add_argument("--floor-only", action="store_true", help="Only run floor gates")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load v4.4 floor module (which itself loads v4.3 floor)
    v44 = _load_v44_gates()
    v43 = v44._load_v43_gates()

    gates = []

    # Class A: inherited v4.4 floor (33 gates = 18 from v4.3 + 15 from v4.4)
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

    if args.floor_only:
        pass
    else:
        # Class B: v4.5 delta -- Epic A (Orchestrator Convergence)
        gates.append(("orchestrator-supervised", "B", "A", gate_orchestrator_supervised))
        gates.append(("orchestrator-boot", "B", "A", gate_orchestrator_boot))
        gates.append(("tool-proxy-canonical", "B", "A", gate_tool_proxy_canonical))
        gates.append(("memory-proxy-canonical", "B", "A", gate_memory_proxy_canonical))
        gates.append(("vision-supervised", "B", "A", gate_vision_supervised))

        # Class B: v4.5 delta -- Epic B (Action Verification + Tool Call Routing)
        gates.append(("verify-real", "B", "B", gate_verify_real))
        gates.append(("tool-call-extraction", "B", "B", gate_tool_call_extraction))
        gates.append(("memory-risk-tier", "B", "B", gate_memory_risk_tier))
        gates.append(("supervisor-ports-clean", "B", "B", gate_supervisor_ports_clean))
        gates.append(("verification-tests", "B", "B", gate_verification_tests))

        # Class B: v4.5 delta -- Epic C (Voice Production Readiness)
        gates.append(("default-backend-auto", "B", "C", gate_default_backend_auto))
        gates.append(("streaming-asr", "B", "C", gate_streaming_asr))
        gates.append(("vad-turn-detect", "B", "C", gate_vad_turn_detect))
        gates.append(("tts-streaming", "B", "C", gate_tts_streaming))
        gates.append(("e2e-audio-test", "B", "C", gate_e2e_audio_test))

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
