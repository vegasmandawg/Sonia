"""Clean-room parity gate: verifies frozen deps, lock file, and env consistency."""
import json, os, sys, datetime, hashlib

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: requirements-frozen.txt exists at root
frozen_path = os.path.join(ROOT, "requirements-frozen.txt")
checks.append({
    "name": "frozen_deps_exist",
    "passed": os.path.isfile(frozen_path),
    "detail": f"requirements-frozen.txt exists: {os.path.isfile(frozen_path)}",
})

# Check 2: Frozen deps has pinned versions (==)
if os.path.isfile(frozen_path):
    with open(frozen_path, "r") as f:
        frozen_lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    pinned = [l for l in frozen_lines if "==" in l]
    pct = len(pinned) / len(frozen_lines) * 100 if frozen_lines else 0
    all_pinned = pct >= 90  # 90%+ must be pinned
else:
    pinned, frozen_lines, pct, all_pinned = [], [], 0, False
checks.append({
    "name": "deps_pinned",
    "passed": all_pinned,
    "detail": f"Pinned: {len(pinned)}/{len(frozen_lines)} ({pct:.0f}%)",
})

# Check 3: dependency-lock.json exists
lock_paths = [
    os.path.join(ROOT, "dependency-lock.json"),
    os.path.join(ROOT, "config", "dependency-lock.json"),
]
lock_exists = any(os.path.isfile(p) for p in lock_paths)
checks.append({
    "name": "dependency_lock_exists",
    "passed": lock_exists,
    "detail": f"dependency-lock.json exists: {lock_exists}",
})

# Check 4: Lock file has SHA-256 hashes
lock_has_sha = False
for p in lock_paths:
    if os.path.isfile(p):
        with open(p, "r") as f:
            lock_content = f.read()
        lock_has_sha = "sha256" in lock_content.lower()
        break
checks.append({
    "name": "lock_has_hashes",
    "passed": lock_has_sha,
    "detail": f"Lock file contains SHA-256 hashes: {lock_has_sha}",
})

# Check 5: Shared version.py exists with SONIA_VERSION
ver_path = os.path.join(ROOT, "services", "shared", "version.py")
if os.path.isfile(ver_path):
    with open(ver_path, "r") as f:
        ver_src = f.read()
    has_version = "SONIA_VERSION" in ver_src
else:
    has_version = False
checks.append({
    "name": "shared_version",
    "passed": has_version,
    "detail": f"Shared version.py with SONIA_VERSION: {has_version}",
})

# Check 6: Python env matches expected
python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
env_exists = os.path.isfile(python)
checks.append({
    "name": "python_env",
    "passed": env_exists,
    "detail": f"sonia-core env exists: {env_exists}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "cleanroom_parity",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"cleanroom-parity-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Clean-Room Parity Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")
print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
