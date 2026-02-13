"""
Integration test configuration.

Registers custom markers for test isolation:
  - legacy_v26_v28: known import-path issues (v2.6-v2.8)
  - legacy_voice_turn_router: old app.voice_turn_router import path
  - legacy_manifest_schema: deleted datasets.manifests.schema module
  - infra_flaky: infrastructure/timing-dependent tests (non-blocking)

Tracked issues:
  - LEGACY-IMPORT-VOICE-TURN-ROUTER
  - LEGACY-MANIFEST-SCHEMA-ADAPTER
  - INFRA-FLAKY-OLLAMA-TIMING
  - INFRA-FLAKY-CHAOS-TIMING
"""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "legacy_v26_v28: legacy compatibility tests (v2.6-v2.8) with known import issues",
    )
    config.addinivalue_line(
        "markers",
        "legacy_voice_turn_router: tests using old app.voice_turn_router import path",
    )
    config.addinivalue_line(
        "markers",
        "legacy_manifest_schema: tests importing deleted datasets.manifests.schema module",
    )
    config.addinivalue_line(
        "markers",
        "infra_flaky: infrastructure/timing-dependent tests (Ollama latency, WS races, chaos timing)",
    )
