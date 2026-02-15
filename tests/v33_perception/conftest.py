"""Shared test setup for v3.3 perception privacy hardening tests (Epic C).

Registers perception, api-gateway, and shared modules so tests can import
PerceptionActionGate, ConfirmationBatcher, EventNormalizer, ProvenanceChain,
and the new v3.3 perception privacy modules.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVA_OS_DIR = REPO_ROOT / "services" / "eva-os"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
PERCEPTION_DIR = REPO_ROOT / "services" / "perception"
SHARED_DIR = REPO_ROOT / "services" / "shared"

for d in [GATEWAY_DIR, EVA_OS_DIR, SHARED_DIR]:
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

# Perception is a package (has __init__.py) -- add parent so
# `from perception.xxx import ...` works, but also add the dir itself
# for bare `from event_normalizer import ...` style.
perception_parent = str(PERCEPTION_DIR.parent)
if perception_parent not in sys.path:
    sys.path.insert(0, perception_parent)
if str(PERCEPTION_DIR) not in sys.path:
    sys.path.insert(0, str(PERCEPTION_DIR))


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


# Pre-load gateway modules
_load_module("perception_action_gate", GATEWAY_DIR / "perception_action_gate.py")

# Pre-load perception modules (may need stubs for imports)
_load_module("event_normalizer", PERCEPTION_DIR / "event_normalizer.py")

# Pre-load v3.3 modules (may not exist yet -- graceful skip)
_load_module("privacy_gate", PERCEPTION_DIR / "privacy_gate.py")
_load_module("zero_frame_enforcer", PERCEPTION_DIR / "zero_frame_enforcer.py")
