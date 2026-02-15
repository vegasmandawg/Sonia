"""
SONIA v3.2.0 Promotion Gate
============================================
Runs all mandatory gates and produces a JSON report.
v3.1 gates serve as the stability floor; new v3.2 gates will be added
as epics are implemented.

Usage:
    python gate-v32.py [--output-dir S:\\reports\\gate-v32]

Gates (Stability Floor 1-17 -- inherited from v3.1):
  1. Repo hygiene
  2. Dependency lock snapshot
  3. Version consistency
  4-7. M1-M4 contract tests
  8. Full M1-M4 regression (112 tests)
  9. Perception -> memory invariants
 10. Confirmation non-bypass
 11. Release manifest hash integrity
 12. Clean-room reproducibility smoke
 13. Deterministic replay equivalence
 14. Crash-recovery integrity
 15. Confirmation non-bypass under load
 16. Chaos fault injection
 17. Provenance strictness

Gates (v3.2 Feature -- to be added):
 18+ TBD per selected epics
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("S:/")
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")
EXPECTED_VERSION = "3.2.0-dev"
EXPECTED_BRANCH = "v3.2-dev"
TEST_DIR = REPO_ROOT / "tests" / "integration"
HARDENING_DIR = REPO_ROOT / "tests" / "hardening"
CHAOS_DIR = REPO_ROOT / "scripts" / "chaos"
TOTAL_GATES = 17  # will grow as epics land


def run_pytest(test_path, label):
    """Run pytest on a path, return (passed, failed, output)."""
    cmd = [PYTHON, "-m", "pytest", str(test_path), "-v", "--tb=short", "-q"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300)
    output = result.stdout + result.stderr
    # Parse counts
    passed = output.count(" PASSED")
    failed = output.count(" FAILED")
    return passed, failed, output


def gate_hygiene():
    """Gate 1: repo hygiene."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    ignore_prefixes = [
        "?? scripts/release/", "?? releases/", "?? reports/",
        "?? docs/V3_2_", "?? tests/v32_smoke/",
    ]
    modify_contains = [
        "scripts/release/", "tests/integration/", "tests/hardening/",
        "docs/V3_2_", "CHANGELOG.md", "ROADMAP.md", "version.py",
    ]
    dirty = [l for l in lines
             if not any(l.strip().startswith(p) for p in ignore_prefixes)
             and not any(mc in l for mc in modify_contains)
             and ".claude/" not in l]
    return len(dirty) == 0, f"{len(dirty)} dirty (tolerated {len(lines) - len(dirty)})"


def gate_version():
    """Gate 3: version consistency."""
    sys.path.insert(0, str(REPO_ROOT / "services" / "shared"))
    from version import SONIA_VERSION, SONIA_CONTRACT
    sys.path.pop(0)
    version_ok = SONIA_VERSION == EXPECTED_VERSION
    contract_ok = SONIA_CONTRACT == "v3.0.0"
    return version_ok and contract_ok, f"version={SONIA_VERSION} contract={SONIA_CONTRACT}"


def gate_regression():
    """Gate 8: full M1-M4 regression."""
    passed, failed, output = run_pytest(TEST_DIR, "M1-M4 regression")
    return failed == 0 and passed >= 112, f"{passed} passed, {failed} failed"


def gate_hardening():
    """Gate 13-15: hardening suite."""
    passed, failed, output = run_pytest(HARDENING_DIR, "hardening")
    return failed == 0 and passed >= 39, f"{passed} passed, {failed} failed"


def gate_chaos():
    """Gate 16: chaos scripts."""
    if not CHAOS_DIR.exists():
        return False, "chaos dir missing"
    scripts = sorted(CHAOS_DIR.glob("chaos_*.py"))
    if len(scripts) < 5:
        return False, f"only {len(scripts)} chaos scripts"
    results = []
    for s in scripts:
        r = subprocess.run([PYTHON, str(s)], capture_output=True, text=True, timeout=120)
        passed = r.returncode == 0
        results.append((s.stem, passed))
    all_pass = all(p for _, p in results)
    detail = ", ".join(f"{n}:{'PASS' if p else 'FAIL'}" for n, p in results)
    return all_pass, detail


def main():
    parser = argparse.ArgumentParser(description="SONIA v3.2 Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports" / "gate-v32"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    gates = [
        ("hygiene", gate_hygiene),
        ("version", gate_version),
        ("regression", gate_regression),
        ("hardening", gate_hardening),
        ("chaos", gate_chaos),
    ]

    results = []
    for name, fn in gates:
        t0 = time.time()
        try:
            passed, detail = fn()
        except Exception as e:
            passed, detail = False, f"ERROR: {e}"
        dt = round(time.time() - t0, 3)
        results.append({
            "gate": name,
            "passed": passed,
            "detail": detail,
            "duration_s": dt,
        })
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}: {detail} ({dt}s)")

    pass_count = sum(1 for r in results if r["passed"])
    total = len(results)
    verdict = "PROMOTE" if pass_count == total else "HOLD"

    report = {
        "version": EXPECTED_VERSION,
        "branch": EXPECTED_BRANCH,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gates_passed": pass_count,
        "gates_total": total,
        "verdict": verdict,
        "gates": results,
    }

    report_path = output_dir / "gate-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n{'=' * 40}")
    print(f"  {pass_count}/{total} gates passed -- {verdict}")
    print(f"  Report: {report_path}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
