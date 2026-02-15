"""Shared test setup for v3.2 voice tests.

Registers the voice package hierarchy in sys.modules so relative imports
within voice modules work when loaded by tests.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPECAT_DIR = REPO_ROOT / "services" / "pipecat"
VOICE_DIR = PIPECAT_DIR / "voice"

# Register parent packages so relative imports in voice modules work
_packages = [
    ("services", REPO_ROOT / "services"),
    ("services.pipecat", PIPECAT_DIR),
    ("services.pipecat.voice", VOICE_DIR),
]
for pkg_name, pkg_dir in _packages:
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def _load_voice(module_name: str):
    """Load a module from services/pipecat/voice/ with package context."""
    full_name = f"services.pipecat.voice.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    file_path = VOICE_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        full_name, file_path,
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "services.pipecat.voice"
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load all modules in dependency order so tests can just import them
_load_voice("turn_events")
_load_voice("turn_state")
_load_voice("turn_reducer")
_load_voice("cancel_registry")
_load_voice("latency_metrics")
_load_voice("turn_router")
