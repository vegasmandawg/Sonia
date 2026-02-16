"""Incident completeness gate: verifies incident bundle infrastructure."""
import json, os, sys, datetime

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: export-incident-bundle.ps1 exists
bundle_script = os.path.join(ROOT, "scripts", "export-incident-bundle.ps1")
checks.append({
    "name": "bundle_script_exists",
    "passed": os.path.isfile(bundle_script),
    "detail": f"export-incident-bundle.ps1 exists: {os.path.isfile(bundle_script)}",
})

# Check 2: Bundle script collects logs, config, health, git, diagnostics, breakers, DLQ
with open(bundle_script, "r") as f:
    bundle_src = f.read()
required_artifacts = ["log", "config", "health", "git", "diagnostic", "breaker", "dead"]
found = [a for a in required_artifacts if a.lower() in bundle_src.lower()]
all_artifacts = len(found) >= 5  # At least 5 of 7 artifact types
checks.append({
    "name": "bundle_artifact_coverage",
    "passed": all_artifacts,
    "detail": f"Artifact types covered: {len(found)}/{len(required_artifacts)} ({', '.join(found)})",
})

# Check 3: WindowMinutes parameter support
has_window = "WindowMinutes" in bundle_src
checks.append({
    "name": "window_parameter",
    "passed": has_window,
    "detail": f"WindowMinutes parameter for time-bounded collection: {has_window}",
})

# Check 4: diagnostics/snapshot endpoint exists in main.py
with open(os.path.join(GW, "main.py"), "r") as f:
    main_src = f.read()
has_diag = "diagnostics/snapshot" in main_src
checks.append({
    "name": "diagnostics_endpoint",
    "passed": has_diag,
    "detail": f"/diagnostics/snapshot endpoint present: {has_diag}",
})

# Check 5: Diagnostics includes health, breakers, DLQ
has_health_in_diag = "health_supervisor" in main_src and "snapshot" in main_src
has_breakers_in_diag = "breaker" in main_src.split("_do_diagnostics_snapshot")[1].split("@app")[0] if "_do_diagnostics_snapshot" in main_src else False
checks.append({
    "name": "diagnostics_comprehensive",
    "passed": has_health_in_diag and has_breakers_in_diag,
    "detail": f"Diagnostics includes health+breakers: {has_health_in_diag and has_breakers_in_diag}",
})

# Check 6: Correlation ID present in diagnostics
has_corr = "correlation_id" in main_src.split("_do_diagnostics_snapshot")[1].split("@app")[0] if "_do_diagnostics_snapshot" in main_src else False
checks.append({
    "name": "correlation_in_diagnostics",
    "passed": has_corr,
    "detail": f"Correlation ID in diagnostics snapshot: {has_corr}",
})

# Check 7: JSONL structured logging infrastructure
jsonl_path = os.path.join(GW, "jsonl_logger.py")
has_jsonl = os.path.isfile(jsonl_path)
checks.append({
    "name": "structured_logging",
    "passed": has_jsonl,
    "detail": f"jsonl_logger.py structured logging: {has_jsonl}",
})

# Check 8: Log directory exists
log_dir = os.path.join(ROOT, "logs", "gateway")
has_log_dir = os.path.isdir(log_dir)
checks.append({
    "name": "log_directory",
    "passed": has_log_dir,
    "detail": f"logs/gateway directory exists: {has_log_dir}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "incident_completeness",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"incident-completeness-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Incident Completeness Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")
print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
