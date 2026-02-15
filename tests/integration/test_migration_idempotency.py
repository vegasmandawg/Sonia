#!/usr/bin/env python3
"""
Migration idempotency and data preservation integration test.

Proves:
  1. Fresh DB -> migrate -> all tables exist
  2. Re-run migration -> idempotent (no errors, no duplicates)
  3. Data inserted pre-migration survives re-run
  4. Schema version tracking is correct
  5. Gate artifact produced in reports/audit/migration-verify-*.json
"""

import sys
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "memory-engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "memory-engine" / "db" / "migrations"))

import pytest

# tests/integration/ is two levels below repo root S:\
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "services" / "memory-engine" / "schema.sql"
MIGRATION_DIR = REPO_ROOT / "services" / "memory-engine" / "db" / "migrations"


def _run_schema(db_path: str):
    """Apply base schema to a fresh database."""
    conn = sqlite3.connect(db_path)
    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def _run_migrations(db_path: str):
    """Import and run the migration runner."""
    import importlib.util
    runner_path = MIGRATION_DIR / "run_migrations.py"
    spec = importlib.util.spec_from_file_location("_mig_runner", runner_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run_migrations_sync(db_path)


def _get_tables(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _get_applied_migrations(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM schema_migrations ORDER BY name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh temporary database."""
    db_path = str(tmp_path / "test_migration.db")
    return db_path


@pytest.fixture(scope="module")
def gate_report():
    """Collect gate report data for audit artifact."""
    report = {
        "gate": "migration-verify",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "overall": "PENDING",
    }
    yield report
    # Write artifact on teardown
    report["overall"] = "PASS" if all(c["passed"] for c in report["checks"]) else "FAIL"
    artifact_dir = REPO_ROOT / "reports" / "audit"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "migration-verify-{}.json".format(
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nGate artifact: {artifact_path}")


def test_fresh_db_schema_and_migrate(fresh_db, gate_report):
    """Fresh DB -> schema -> migrate -> all expected tables exist."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    tables = _get_tables(fresh_db)
    expected = {
        "schema_version", "ledger", "ledger_search", "snapshots",
        "audit_log", "workspace_documents", "workspace_chunks",
        "provenance", "schema_migrations", "ledger_events",
    }
    missing = expected - tables
    gate_report["checks"].append({
        "name": "fresh_db_tables",
        "passed": len(missing) == 0,
        "tables_found": sorted(tables),
        "missing": sorted(missing),
    })
    assert len(missing) == 0, f"Missing tables: {missing}"


def test_migration_tracking(fresh_db, gate_report):
    """All 9 numbered SQL files are tracked in schema_migrations."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    applied = _get_applied_migrations(fresh_db)
    sql_files = sorted(f.name for f in MIGRATION_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    gate_report["checks"].append({
        "name": "migration_tracking",
        "passed": applied == sql_files,
        "applied": applied,
        "expected": sql_files,
    })
    assert applied == sql_files, f"Applied {applied} != expected {sql_files}"


def test_idempotent_rerun(fresh_db, gate_report):
    """Re-running migration after initial apply produces no errors."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    # Run again - must not raise
    error = None
    try:
        _run_migrations(fresh_db)
    except Exception as e:
        error = str(e)

    applied_after = _get_applied_migrations(fresh_db)
    sql_files = sorted(f.name for f in MIGRATION_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    gate_report["checks"].append({
        "name": "idempotent_rerun",
        "passed": error is None and applied_after == sql_files,
        "error": error,
        "migration_count_after": len(applied_after),
    })
    assert error is None, f"Re-run raised: {error}"
    assert applied_after == sql_files, "Migration count changed on re-run"


def test_data_preservation(fresh_db, gate_report):
    """Data inserted before re-migration survives the re-run."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    # Insert test data
    test_id = f"mem_test_{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(fresh_db)
    try:
        conn.execute(
            "INSERT INTO ledger (id, type, content, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (test_id, "fact", "migration test data", "{}", now, now),
        )
        conn.commit()
    finally:
        conn.close()

    # Re-run migrations
    _run_migrations(fresh_db)

    # Verify data survived
    conn = sqlite3.connect(fresh_db)
    try:
        row = conn.execute("SELECT content FROM ledger WHERE id = ?", (test_id,)).fetchone()
    finally:
        conn.close()

    survived = row is not None and row[0] == "migration test data"
    gate_report["checks"].append({
        "name": "data_preservation",
        "passed": survived,
        "test_id": test_id,
        "found_after_rerun": row is not None,
    })
    assert survived, "Test data did not survive re-migration"


def test_schema_version_exists(fresh_db, gate_report):
    """schema_version table exists and has initial version record."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    conn = sqlite3.connect(fresh_db)
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    finally:
        conn.close()

    has_version = row is not None and row[0] == 1
    gate_report["checks"].append({
        "name": "schema_version_record",
        "passed": has_version,
        "version": row[0] if row else None,
    })
    assert has_version, "schema_version table missing initial record"


def test_wal_mode_after_migration(fresh_db, gate_report):
    """WAL mode is correctly set after migration run."""
    _run_schema(fresh_db)
    _run_migrations(fresh_db)

    # Open with the MemoryDatabase wrapper to get pragma enforcement
    sys.path.insert(0, str(REPO_ROOT / "services" / "memory-engine"))
    import importlib
    db_mod = importlib.import_module("db")
    db = db_mod.MemoryDatabase(db_path=fresh_db)
    result = db.verify_pragmas()

    gate_report["checks"].append({
        "name": "wal_mode_enforcement",
        "passed": result["all_ok"],
        "pragmas": {k: v for k, v in result.items() if k not in ("all_ok", "expected")},
    })
    assert result["all_ok"], f"Pragma verification failed: {result}"
