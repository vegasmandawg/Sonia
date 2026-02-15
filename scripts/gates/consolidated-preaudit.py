#!/usr/bin/env python3
"""
Consolidated pre-audit gate.

Runs all evidence gates in sequence and produces a single pass/fail report.
Gates:
  1. Secret scan (P01 class)
  2. Redaction verification (Q01 class)
  3. Migration verify (M01-M06)
  4. Backup-restore drill (U01-U06)
  5. Incident bundle (N01, V02)
  6. Control traceability (W, A, N, P, Q)
  7. Runbook headings validation
  8. Pragma health evidence

Produces: reports/audit/consolidated-preaudit-*.json
"""

import sys
import json
import subprocess
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATES_DIR = REPO_ROOT / "scripts" / "gates"
REPORT_DIR = REPO_ROOT / "reports" / "audit"
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")

REQUIRED_RUNBOOK_HEADINGS = {
    "DEPLOYMENT.md": ["Prerequisites", "Environment", "Configuration", "Known Limitations"],
    "OPERATIONS_RUNBOOK.md": ["Start", "Stop", "Health", "Failure", "Incident", "Known Limitations"],
    "SECURITY_MODEL.md": ["Threat", "Secrets", "Auth", "Redaction", "Known Limitations"],
    "PRIVACY_MODEL.md": ["Data", "Redaction", "Perception", "Retention", "Known Limitations"],
    "TROUBLESHOOTING.md": ["Service", "Health", "Memory", "DLQ", "Breaker", "Latency"],
    "BACKUP_RECOVERY.md": ["RPO", "RTO", "Backup", "Restore", "Drill", "Known Limitations"],
}


def run_gate(name: str, script_path: str, extra_args: list = None) -> dict:
    """Run a gate script and capture result."""
    args = [PYTHON, script_path] + (extra_args or [])
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT)
        )
        return {
            "gate": name,
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": result.stdout.strip()[-500:] if result.stdout else "",
            "stderr_tail": result.stderr.strip()[-200:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"gate": name, "passed": False, "exit_code": -1, "error": "timeout"}
    except Exception as e:
        return {"gate": name, "passed": False, "exit_code": -1, "error": str(e)}


def run_pytest_gate(name: str, test_path: str) -> dict:
    """Run a pytest test file as a gate."""
    args = [PYTHON, "-m", "pytest", test_path, "-v", "--no-header", "--tb=short", "-q"]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT)
        )
        return {
            "gate": name,
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": result.stdout.strip()[-500:] if result.stdout else "",
        }
    except subprocess.TimeoutExpired:
        return {"gate": name, "passed": False, "exit_code": -1, "error": "timeout"}
    except Exception as e:
        return {"gate": name, "passed": False, "exit_code": -1, "error": str(e)}


def check_runbook_headings() -> dict:
    """Verify required headings exist in each ops doc."""
    missing = {}
    for doc, required_words in REQUIRED_RUNBOOK_HEADINGS.items():
        path = REPO_ROOT / "docs" / doc
        if not path.exists():
            missing[doc] = ["FILE MISSING"]
            continue
        content = path.read_text(encoding="utf-8").lower()
        doc_missing = [w for w in required_words if w.lower() not in content]
        if doc_missing:
            missing[doc] = doc_missing
    return {
        "gate": "runbook_headings",
        "passed": len(missing) == 0,
        "docs_checked": len(REQUIRED_RUNBOOK_HEADINGS),
        "missing": missing if missing else None,
    }


def check_pragma_evidence() -> dict:
    """Verify WAL pragmas on a fresh temp DB."""
    sys.path.insert(0, str(REPO_ROOT / "services" / "memory-engine"))
    try:
        from db import MemoryDatabase
        tmp = tempfile.mktemp(suffix=".db")
        db = MemoryDatabase(db_path=tmp)
        result = db.verify_pragmas()
        Path(tmp).unlink(missing_ok=True)
        for wal_file in Path(tmp).parent.glob(Path(tmp).name + "*"):
            wal_file.unlink(missing_ok=True)
        return {
            "gate": "pragma_health",
            "passed": result["all_ok"],
            "pragmas": {k: v for k, v in result.items() if k not in ("all_ok", "expected")},
        }
    except Exception as e:
        return {"gate": "pragma_health", "passed": False, "error": str(e)}


def main():
    print("=" * 60)
    print("SONIA Consolidated Pre-Audit Gate")
    print("=" * 60)
    print()

    gates = []

    # Gate 1: Secret scan
    print("[1/8] Secret scan...")
    gates.append(run_gate("secret_scan", str(GATES_DIR / "secret-scan-gate.py")))

    # Gate 2: Redaction verification
    print("[2/8] Redaction verification...")
    gates.append(run_pytest_gate(
        "redaction_verify",
        str(REPO_ROOT / "tests" / "integration" / "test_log_redaction_verification.py")
    ))

    # Gate 3: Migration verify
    print("[3/8] Migration idempotency...")
    gates.append(run_pytest_gate(
        "migration_verify",
        str(REPO_ROOT / "tests" / "integration" / "test_migration_idempotency.py")
    ))

    # Gate 4: Backup-restore drill
    print("[4/8] Backup-restore drill...")
    gates.append(run_gate("backup_restore_drill", str(GATES_DIR / "backup-restore-drill.py")))

    # Gate 5: Incident bundle
    print("[5/8] Incident bundle...")
    gates.append(run_gate("incident_bundle", str(GATES_DIR / "incident-bundle-gate.py")))

    # Gate 6: Control traceability
    print("[6/8] Control traceability...")
    gates.append(run_gate("control_traceability", str(GATES_DIR / "traceability-gate.py")))

    # Gate 7: Runbook headings
    print("[7/8] Runbook headings...")
    gates.append(check_runbook_headings())

    # Gate 8: Pragma health
    print("[8/8] Pragma health...")
    gates.append(check_pragma_evidence())

    # Summary
    print()
    print("-" * 60)
    passed = sum(1 for g in gates if g["passed"])
    total = len(gates)
    overall = "PASS" if passed == total else "FAIL"

    for g in gates:
        tag = "PASS" if g["passed"] else "FAIL"
        print(f"  [{tag}] {g['gate']}")

    print(f"\n{passed}/{total} gates passed")

    # Build manifest
    report = {
        "gate": "consolidated-preaudit",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gates_total": total,
        "gates_passed": passed,
        "overall": overall,
        "gates": gates,
    }

    # SHA-256 of the report for tamper evidence
    report_json = json.dumps(report, indent=2, sort_keys=True)
    report["manifest_sha256"] = hashlib.sha256(report_json.encode()).hexdigest()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = REPORT_DIR / "consolidated-preaudit-{}.json".format(
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {artifact}")
    print(f"\n{overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
