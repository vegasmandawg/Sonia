"""
Integration test configuration.

Registers custom markers and provides canonical module loaders so that
tests never need to manipulate sys.path or use fragile lazy imports.

Canonical loaders:
  - voice_turn_router_mod: loads VoiceTurnRouter + VoiceTurnRecord
  - gateway_stream_client_mod: loads GatewayStreamClient + helpers

Custom markers:
  - legacy_v26_v28: legacy compatibility tests (v2.6-v2.8)
  - legacy_manifest_schema: deleted datasets.manifests.schema module
  - infra_flaky: infrastructure/timing-dependent tests (non-blocking)
"""

import os
import sys
import types
import importlib.util
import pytest

# ---------------------------------------------------------------------------
# Repo root detection — works on local dev (S:\) and CI (D:\a\Sonia\Sonia\)
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Canonical module loaders — load by absolute file path, no sys.path hacks.
# Register in sys.modules so downstream imports resolve correctly.
#
# When a source file is missing (CI), a stub module is registered so that
# downstream ``from <name> import Foo`` resolves to None instead of raising
# ModuleNotFoundError during pytest collection.
# ---------------------------------------------------------------------------

def _load_module(name: str, filepath: str):
    """Load a Python module by absolute file path.

    Returns a stub module if the file does not exist (CI environments may
    not have all service code available).  The stub is registered in
    sys.modules so that ``from <name> import X`` yields None for any X.
    """
    if name in sys.modules:
        return sys.modules[name]
    if not os.path.isfile(filepath):
        # Register a permissive stub so ``from name import Foo`` -> None
        stub = types.ModuleType(name)
        stub.__file__ = filepath
        stub.__doc__ = f"CI stub for {name} (source not found: {filepath})"
        stub.__getattr__ = lambda attr: None  # any attribute -> None
        sys.modules[name] = stub
        return stub
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _repo_path(*parts: str) -> str:
    """Build an absolute path relative to the repository root."""
    return os.path.join(_REPO_ROOT, *parts)


# VoiceTurnRouter + VoiceTurnRecord
_vtr_mod = _load_module(
    "pipecat_voice_turn_router",
    _repo_path("services", "pipecat", "app", "voice_turn_router.py"),
)
VoiceTurnRouter = getattr(_vtr_mod, "VoiceTurnRouter", None)
VoiceTurnRecord = getattr(_vtr_mod, "VoiceTurnRecord", None)

# GatewayStreamClient
_gsc_mod = _load_module(
    "pipecat_gateway_stream_client",
    _repo_path("services", "pipecat", "clients", "gateway_stream_client.py"),
)


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "legacy_v26_v28: legacy compatibility tests (v2.6-v2.8)",
    )
    config.addinivalue_line(
        "markers",
        "legacy_manifest_schema: tests importing deleted datasets.manifests.schema module",
    )
    config.addinivalue_line(
        "markers",
        "infra_flaky: infrastructure/timing-dependent tests (Ollama latency, WS races, chaos timing)",
    )


# ---------------------------------------------------------------------------
# Session-scoped model warmup — ensures Ollama model is loaded before any
# integration test that hits the /v1/turn endpoint.
# ---------------------------------------------------------------------------

import asyncio
import httpx

_GW = "http://127.0.0.1:7000"
_MODEL_WARM = False


async def _do_warmup():
    """Send throwaway /v1/turn requests until ok=true (up to 5 attempts)."""
    global _MODEL_WARM
    if _MODEL_WARM:
        return
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(f"{_GW}/v1/turn", json={
                    "user_id": "warmup",
                    "conversation_id": f"warmup-conftest-{attempt}",
                    "input_text": "ping",
                })
                if r.json().get("ok"):
                    _MODEL_WARM = True
                    return
        except Exception:
            pass
        await asyncio.sleep(3.0)
    _MODEL_WARM = True  # proceed even if warmup failed


@pytest.fixture(scope="session", autouse=True)
def warmup_model():
    """Session-scoped sync fixture that warms the model once before all tests."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    loop.run_until_complete(_do_warmup())
