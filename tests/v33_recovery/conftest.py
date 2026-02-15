"""Shared test setup for v3.3 recovery tests (Epic B).

Registers the eva-os, api-gateway, and shared modules so tests can import
ServiceSupervisor, HealthSupervisor, StateBackupManager, CircuitBreaker,
RetryTaxonomy, and the new v3.3 recovery modules.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVA_OS_DIR = REPO_ROOT / "services" / "eva-os"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
SHARED_DIR = REPO_ROOT / "services" / "shared"

# Ensure gateway dir is on path for bare imports used by some modules
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
if str(EVA_OS_DIR) not in sys.path:
    sys.path.insert(0, str(EVA_OS_DIR))
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


def _load_module(name: str, file_path: Path):
    """Load a module by absolute file path."""
    if name in sys.modules:
        return sys.modules[name]
    if not file_path.exists():
        return None  # module not yet implemented
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[name]
        return None
    return mod


# Pre-load existing modules needed by tests
_load_module("service_supervisor", EVA_OS_DIR / "service_supervisor.py")
_load_module("circuit_breaker", GATEWAY_DIR / "circuit_breaker.py")
_load_module("retry_taxonomy", GATEWAY_DIR / "retry_taxonomy.py")
_load_module("state_backup", GATEWAY_DIR / "state_backup.py")
_load_module("health_supervisor", GATEWAY_DIR / "health_supervisor.py")

# Pre-load v3.3 modules (may not exist yet -- graceful skip)
_load_module("restore_verifier", EVA_OS_DIR / "restore_verifier.py")
_load_module("triage_recommender", EVA_OS_DIR / "triage_recommender.py")
_load_module("operator_drill", EVA_OS_DIR / "operator_drill.py")
