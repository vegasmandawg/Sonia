"""Shared test setup for v3.2 perception tests.

Registers the perception package hierarchy in sys.modules so relative imports
within perception modules work when loaded by tests.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PERCEPTION_DIR = REPO_ROOT / "services" / "perception"

# Register parent packages so relative imports in perception modules work
_packages = [
    ("services", REPO_ROOT / "services"),
    ("services.perception", PERCEPTION_DIR),
]
for pkg_name, pkg_dir in _packages:
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def _load_perception(module_name: str):
    """Load a module from services/perception/ with package context."""
    full_name = f"services.perception.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    file_path = PERCEPTION_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        full_name, file_path,
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "services.perception"
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load all modules in dependency order
_load_perception("event_normalizer")
_load_perception("dedupe_engine")
_load_perception("priority_router")
_load_perception("confirmation_batcher")
_load_perception("provenance_hooks")
_load_perception("policy")
