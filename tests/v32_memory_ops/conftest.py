"""Shared test setup for v3.2 memory ops tests.

Registers the memory_ops package hierarchy in sys.modules so relative
imports within memory_ops modules work when loaded by tests.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_OPS_DIR = REPO_ROOT / "services" / "memory_ops"

# Register parent packages so relative imports work
_packages = [
    ("services", REPO_ROOT / "services"),
    ("services.memory_ops", MEMORY_OPS_DIR),
]
for pkg_name, pkg_dir in _packages:
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def _load_memory_ops(module_name: str):
    """Load a module from services/memory_ops/ with package context."""
    full_name = f"services.memory_ops.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    file_path = MEMORY_OPS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        full_name, file_path,
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "services.memory_ops"
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load all modules in dependency order
_load_memory_ops("proposal_model")
_load_memory_ops("proposal_policy")
_load_memory_ops("proposal_queue")
_load_memory_ops("conflict_detector")
_load_memory_ops("provenance")
_load_memory_ops("governance_pipeline")
_load_memory_ops("replay_engine")
