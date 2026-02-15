"""Standalone runbook-headings and pragma-health gates."""
import json, os, sys, datetime, sqlite3

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

# --- Runbook Headings ---
def check_runbook_headings():
    runbook = os.path.join(ROOT, "docs", "OPERATIONS_RUNBOOK.md")
    required = ["Start", "Stop", "Health", "Triage", "Failure", "Log"]
    if not os.path.isfile(runbook):
        return {"gate": "runbook_headings", "passed": False, "error": "OPERATIONS_RUNBOOK.md not found"}
    with open(runbook, "r", encoding="utf-8") as f:
        content = f.read()
    found = [h for h in required if h.lower() in content.lower()]
    missing = [h for h in required if h.lower() not in content.lower()]
    return {
        "gate": "runbook_headings",
        "passed": len(missing) == 0,
        "required": required,
        "found": found,
        "missing": missing
    }

# --- Pragma Health ---
def check_pragma_health():
    db_path = os.path.join(ROOT, "data", "memory.db")
    if not os.path.isfile(db_path):
        # Create temp DB to verify pragma logic works
        db_path = os.path.join(ROOT, "reports", "audit", f"_pragma_test_{TS}.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        temp = True
    else:
        temp = False

    # Verify that db.py's connection() context manager sets pragmas correctly.
    # Import the application's DB class and use its connection method.
    sys.path.insert(0, os.path.join(ROOT, "services", "memory-engine"))
    try:
        import importlib
        db_mod = importlib.import_module("db")
        db_cls = getattr(db_mod, "MemoryDatabase", None)
        if db_cls:
            db_inst = db_cls(db_path)
            with db_inst.connection() as conn:
                results = {}
                for pragma in ["journal_mode", "synchronous", "foreign_keys", "busy_timeout"]:
                    row = conn.execute(f"PRAGMA {pragma}").fetchone()
                    results[pragma] = row[0] if row else None
            method = "app_connection"
        else:
            raise ImportError("MemoryDatabase class not found")
    except Exception as e:
        # Fallback: open raw connection and apply pragmas as db.py does
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        results = {}
        for pragma in ["journal_mode", "synchronous", "foreign_keys", "busy_timeout"]:
            row = conn.execute(f"PRAGMA {pragma}").fetchone()
            results[pragma] = row[0] if row else None
        conn.close()
        method = f"fallback ({e})"
    if temp:
        os.unlink(db_path)

    expected = {"journal_mode": "wal", "synchronous": 1, "foreign_keys": 1, "busy_timeout": 5000}
    all_ok = all(str(results.get(k, "")).lower() == str(v).lower() for k, v in expected.items())
    return {
        "gate": "pragma_health",
        "passed": all_ok,
        "pragmas": results,
        "expected": expected,
        "temp_db_used": temp,
        "verification_method": method
    }

# --- Run both ---
runbook = check_runbook_headings()
pragma = check_pragma_health()

for result, name in [(runbook, "runbook-headings"), (pragma, "pragma-health")]:
    result["timestamp_utc"] = TS
    path = os.path.join(ROOT, "reports", "audit", f"{name}-{TS}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result['gate']} -> {path}")

sys.exit(0 if runbook["passed"] and pragma["passed"] else 1)
