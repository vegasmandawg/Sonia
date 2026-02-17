"""
v4.6 Epic B -- Gate B3: Supervisor Restart Budget Persistence Tests

Tests that restart window counters survive process restart via durable storage.
Uses direct module instantiation (no live services required).
"""
import sys
import os
import time
import json
import sqlite3
import tempfile
from pathlib import Path

# Load supervisor module
EVA_DIR = Path(r"S:\services\eva-os")
sys.path.insert(0, str(EVA_DIR))

import importlib.util

def _load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

sup_mod = _load_mod("service_supervisor", EVA_DIR / "service_supervisor.py")
ServiceSupervisor = sup_mod.ServiceSupervisor
ServiceState = sup_mod.ServiceState


def _make_tmp_db():
    """Create a temp SQLite path for testing."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sonia_budget_test_")
    os.close(fd)
    return path


# ── B3 Test Matrix ──

def test_budget_store_class_exists():
    """RestartBudgetStore or equivalent persistence class exists."""
    assert hasattr(sup_mod, "RestartBudgetStore"), \
        "RestartBudgetStore not found in service_supervisor.py"


def test_attempts_persist_across_restart():
    """Restart attempts written to durable store survive re-instantiation."""
    db_path = _make_tmp_db()
    try:
        store1 = sup_mod.RestartBudgetStore(db_path)
        store1.record_attempt("api-gateway", time.time())
        store1.record_attempt("api-gateway", time.time())
        store1.close()

        store2 = sup_mod.RestartBudgetStore(db_path)
        budget = store2.get_budget("api-gateway")
        store2.close()

        assert budget is not None, "Budget should exist after recording attempts"
        assert budget["attempt_count"] >= 2, \
            f"Expected >=2 attempts, got {budget['attempt_count']}"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_backoff_timer_persists():
    """Backoff-until timestamp persists across restart."""
    db_path = _make_tmp_db()
    try:
        store1 = sup_mod.RestartBudgetStore(db_path)
        future = time.time() + 60.0
        store1.update_backoff("model-router", future)
        store1.close()

        store2 = sup_mod.RestartBudgetStore(db_path)
        budget = store2.get_budget("model-router")
        store2.close()

        assert budget is not None
        assert budget["backoff_until_epoch_ms"] >= future * 1000 - 1, \
            f"Backoff timer not persisted: {budget}"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_exhaustion_state_persists():
    """Exhaustion (max restarts reached) persists across restart."""
    db_path = _make_tmp_db()
    try:
        store1 = sup_mod.RestartBudgetStore(db_path)
        now = time.time()
        for i in range(3):
            store1.record_attempt("pipecat", now + i)
        store1.mark_exhausted("pipecat")
        store1.close()

        store2 = sup_mod.RestartBudgetStore(db_path)
        budget = store2.get_budget("pipecat")
        store2.close()

        assert budget is not None
        assert budget.get("exhausted") is True, \
            f"Exhaustion flag not persisted: {budget}"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_window_rollover_resets():
    """When window expires, attempts reset correctly."""
    db_path = _make_tmp_db()
    try:
        store = sup_mod.RestartBudgetStore(db_path)
        old_time = time.time() - 600  # 10 min ago, outside 5-min window
        store.record_attempt("memory-engine", old_time)
        store.record_attempt("memory-engine", old_time + 1)

        # Prune with current window
        store.prune_expired("memory-engine", window_s=300.0)
        budget = store.get_budget("memory-engine")
        store.close()

        assert budget is not None
        assert budget["attempt_count"] == 0, \
            f"Expected 0 after window rollover, got {budget['attempt_count']}"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_multiple_services_isolate_budgets():
    """Each service has its own independent budget."""
    db_path = _make_tmp_db()
    try:
        store = sup_mod.RestartBudgetStore(db_path)
        now = time.time()
        store.record_attempt("api-gateway", now)
        store.record_attempt("api-gateway", now + 1)
        store.record_attempt("model-router", now)

        gw = store.get_budget("api-gateway")
        mr = store.get_budget("model-router")
        pc = store.get_budget("pipecat")
        store.close()

        assert gw["attempt_count"] == 2
        assert mr["attempt_count"] == 1
        assert pc is None or pc["attempt_count"] == 0
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_corrupted_db_fails_closed():
    """Corrupted/invalid DB enters degraded mode: synthetic exhausted budget (fail-closed).

    Policy: corrupted persistence must NOT grant fresh restart attempts.
    The store returns a synthetic budget with exhausted=True and high attempt_count
    so the supervisor refuses to restart any service until the store recovers.
    """
    db_path = _make_tmp_db()
    try:
        # Write garbage to the file
        with open(db_path, "wb") as f:
            f.write(b"THIS IS NOT A DATABASE\x00\xff\xfe")

        store = sup_mod.RestartBudgetStore(db_path)
        # Store should be in degraded mode
        assert store.is_degraded, "Store should be degraded after corruption"

        # get_budget must return exhausted budget (fail-closed, not fail-open)
        budget = store.get_budget("api-gateway")
        store.close()

        assert budget is not None, "Degraded store must return a budget, not None"
        assert budget["exhausted"] is True, \
            f"Degraded budget must be exhausted (fail-closed), got: {budget}"
        assert budget["attempt_count"] >= 3, \
            f"Degraded budget must show high attempt count, got: {budget['attempt_count']}"
        assert budget.get("degraded") is True, \
            "Degraded budget should carry degraded flag for diagnostics"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
