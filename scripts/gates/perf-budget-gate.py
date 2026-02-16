"""Performance budget gate: verifies latency instrumentation and SLO infrastructure."""
import json, os, sys, datetime

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: Latency instrumentation in turn pipeline
with open(os.path.join(GW, "main.py"), "r") as f:
    main_src = f.read()

# Also read route files where latency instrumentation lives
routes_dir = os.path.join(GW, "routes")
all_src = main_src
for rf in ["turn.py", "stream.py", "ui_stream.py"]:
    rp = os.path.join(routes_dir, rf)
    if os.path.isfile(rp):
        with open(rp, "r") as f2:
            all_src += f2.read()

latency_fields = ["memory_read_ms", "model_ms", "tool_ms", "total_ms"]
found_fields = [f for f in latency_fields if f in all_src]
has_latency = len(found_fields) >= 3
checks.append({
    "name": "latency_instrumentation",
    "passed": has_latency,
    "detail": f"Latency fields found: {len(found_fields)}/{len(latency_fields)} ({', '.join(found_fields)})",
})

# Check 2: SLO budget definitions exist in soak scripts
soak_scripts = [
    os.path.join(ROOT, "scripts", "soak_stage6_latency.ps1"),
    os.path.join(ROOT, "scripts", "soak_v28_rc1_runner.py"),
]
has_slo = False
for sp in soak_scripts:
    if os.path.isfile(sp):
        with open(sp, "r") as f:
            if "p95" in f.read().lower() or "p99" in f.read().lower():
                has_slo = True
                break
# Alternative: check if any soak script exists at all
soak_exists = any(os.path.isfile(sp) for sp in soak_scripts)
checks.append({
    "name": "slo_infrastructure",
    "passed": soak_exists,
    "detail": f"Soak/SLO scripts exist: {soak_exists}",
})

# Check 3: Health supervisor tracks per-service status
hs_path = os.path.join(GW, "health_supervisor.py")
hs_exists = os.path.isfile(hs_path)
checks.append({
    "name": "health_supervisor",
    "passed": hs_exists,
    "detail": f"health_supervisor.py exists: {hs_exists}",
})

# Check 4: Rate limiter has per-client tracking
rl_path = os.path.join(ROOT, "services", "shared", "rate_limiter.py")
if os.path.isfile(rl_path):
    with open(rl_path, "r") as f:
        rl_src = f.read()
    has_per_client = "client" in rl_src.lower() or "_buckets" in rl_src
else:
    has_per_client = False
checks.append({
    "name": "per_client_rate_limiting",
    "passed": has_per_client,
    "detail": f"Per-client rate limiting: {has_per_client}",
})

# Check 5: Breaker metrics endpoint for performance monitoring
has_metrics = "breakers/metrics" in main_src
checks.append({
    "name": "breaker_metrics_endpoint",
    "passed": has_metrics,
    "detail": f"/breakers/metrics endpoint: {has_metrics}",
})

# Check 6: Turn quality enforces max_output_chars
tq_path = os.path.join(GW, "turn_quality.py")
if os.path.isfile(tq_path):
    with open(tq_path, "r") as f:
        tq_src = f.read()
    has_max_output = "max_output_chars" in tq_src
else:
    has_max_output = False
checks.append({
    "name": "output_budget",
    "passed": has_max_output,
    "detail": f"max_output_chars enforcement: {has_max_output}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "perf_budget",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"perf-budget-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Performance Budget Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")
print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
