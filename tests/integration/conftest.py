"""
Integration test configuration.

Registers custom markers for legacy test isolation.
Legacy tests (v2.6-v2.8) have known import-path issues that do not
affect production paths. They are tracked under:
  - LEGACY-IMPORT-VOICE-TURN-ROUTER
  - LEGACY-MANIFEST-SCHEMA-ADAPTER
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
