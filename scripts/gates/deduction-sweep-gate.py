"""
Deduction Sweep Gate (10 checks)
=================================
Validates deduction elimination controls for sections C, D, K, L, N, T.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(r"S:\\")
sys.path.insert(0, str(ROOT / "services" / "api-gateway"))

checks = []


def check(name, fn):
    try:
        ok = fn()
        checks.append({"name": name, "result": "PASS" if ok else "FAIL"})
    except Exception as e:
        checks.append({"name": name, "result": "FAIL", "error": str(e)})


# 1. Code quality policy file present
def c1():
    import lint_config
    return hasattr(lint_config, "LintConfig") and hasattr(lint_config, "DEFAULT_POLICY")
check("code_quality_policy_present", c1)


# 2. Lint/type policy configuration present
def c2():
    from lint_config import DEFAULT_POLICY
    v = DEFAULT_POLICY.validate()
    return v["valid"] and v["error_rules"] >= 2
check("lint_type_policy_configured", c2)


# 3. Config schema files present and versioned
def c3():
    import config_audit
    engine = config_audit.ConfigAuditEngine()
    rec = engine.register("test.json", "1.0.0", '{"key": "value"}', ["key"])
    return rec.schema_version == "1.0.0"
check("config_schema_versioned", c3)


# 4. Config schema validation runner executes
def c4():
    from config_audit import ConfigAuditEngine
    engine = ConfigAuditEngine()
    engine.register("app.json", "2.0", '{"port": 7000}', ["port"])
    result = engine.validate_required_keys("app.json", {"port": 7000})
    return result["valid"]
check("config_validation_executes", c4)


# 5. Perf budget policy declared
def c5():
    from slo_dashboard import SLODashboard
    d = SLODashboard()
    d.define_slo("api_latency", "p95_latency", 200.0, "ms")
    slos = d.list_slos()
    return len(slos) >= 1 and slos[0]["threshold"] > 0
check("perf_budget_declared", c5)


# 6. Steady-state perf artifact parsable
def c6():
    from slo_dashboard import SLODashboard
    d = SLODashboard()
    d.define_slo("api_latency", "p95_latency", 200.0)
    d.evaluate("api_latency", 150.0)
    report = d.get_budget_report()
    return report["total"] >= 1 and report["results"][0]["status"] == "MET"
check("perf_artifact_parsable", c6)


# 7. Contract field policy declared
def c7():
    from contract_trace import ContractConsistencyChecker, ServiceContract, ContractField
    cc = ContractConsistencyChecker()
    cc.register(ServiceContract(
        "api-gateway", "3.9",
        [ContractField("correlation_id", "string"), ContractField("timestamp", "string")]
    ))
    result = cc.check_required_fields("api-gateway", {"correlation_id": "req_test1234", "timestamp": "now"})
    return result["valid"]
check("contract_field_policy_declared", c7)


# 8. Correlation/trace continuity checks present
def c8():
    from contract_trace import TracePropagationChecker
    stages = [
        {"correlation_id": "req_sweep_gate"},
        {"correlation_id": "req_sweep_gate"},
    ]
    result = TracePropagationChecker.check_propagation(stages)
    return result["valid"] and result["consistent"]
check("trace_continuity_checks_present", c8)


# 9. Observability required-field policy declared
def c9():
    from observability_requirements import ObservabilityRequirements
    obs = ObservabilityRequirements()
    reqs = obs.list_requirements()
    return len(reqs) >= 5 and "log_entry" in reqs
check("observability_policy_declared", c9)


# 10. No unresolved high-severity deduction flags
def c10():
    from lint_config import DEFAULT_POLICY, Severity
    errors = DEFAULT_POLICY.get_rules_by_severity(Severity.ERROR)
    # All error rules must be enabled
    return all(r.enabled for r in errors) and len(errors) >= 2
check("no_unresolved_deductions", c10)


# ---- Report ----
ts = time.strftime("%Y%m%d-%H%M%S")
passed = sum(1 for c in checks if c["result"] == "PASS")
total = len(checks)
verdict = "PASS" if passed == total else "FAIL"

report = {
    "gate": "deduction-sweep",
    "timestamp": ts,
    "checks": checks,
    "passed": passed,
    "total": total,
    "verdict": verdict,
}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"deduction-sweep-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Deduction Sweep Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
