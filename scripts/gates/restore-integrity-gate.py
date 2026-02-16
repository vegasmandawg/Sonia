"""Restore integrity gate: verifies backup/restore subsystem."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: state_backup.py exists
sb_path = os.path.join(GW, "state_backup.py")
checks.append({
    "name": "state_backup_exists",
    "passed": os.path.isfile(sb_path),
    "detail": f"state_backup.py exists: {os.path.isfile(sb_path)}",
})

# Check 2: SHA-256 checksums in backup
with open(sb_path, "r") as f:
    sb_src = f.read()
has_sha256 = "sha256" in sb_src
checks.append({
    "name": "sha256_checksums",
    "passed": has_sha256,
    "detail": f"SHA-256 checksums in backup: {has_sha256}",
})

# Check 3: verify_backup method exists
has_verify = "async def verify_backup" in sb_src
checks.append({
    "name": "verify_method",
    "passed": has_verify,
    "detail": f"verify_backup method exists: {has_verify}",
})

# Check 4: restore_dlq with dry_run support
has_dry_run = "dry_run" in sb_src and "async def restore_dlq" in sb_src
checks.append({
    "name": "restore_dry_run",
    "passed": has_dry_run,
    "detail": f"restore_dlq with dry_run support: {has_dry_run}",
})

# Check 5: Backup/restore endpoints in main.py
with open(os.path.join(GW, "main.py"), "r") as f:
    main_src = f.read()
has_backup_endpoints = "/v3/backups" in main_src and "restore/dlq" in main_src
checks.append({
    "name": "backup_endpoints",
    "passed": has_backup_endpoints,
    "detail": f"Backup/restore API endpoints present: {has_backup_endpoints}",
})

# Check 6: Unit tests exist and pass
test_path = os.path.join(ROOT, "tests", "unit", "test_restore_integrity.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(test_path),
    "detail": f"test_restore_integrity.py exists: {os.path.isfile(test_path)}",
})

python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable

result = subprocess.run(
    [python, "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT, timeout=120
)
unit_passed = result.returncode == 0
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
checks.append({
    "name": "unit_tests_pass",
    "passed": unit_passed,
    "detail": summary_line,
    "stdout": result.stdout[-500:] if not unit_passed else "",
    "stderr": result.stderr[-300:] if not unit_passed else "",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "restore_integrity",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"restore-integrity-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Restore Integrity Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")
print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
