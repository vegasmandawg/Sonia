"""Canonical version string for the entire SONIA stack.

Import this in every service's main.py to ensure version consistency.

Usage:
    from shared.version import SONIA_VERSION, SONIA_CONTRACT
    app = FastAPI(..., version=SONIA_VERSION)
"""

SONIA_VERSION = "3.1.0"
SONIA_CONTRACT = "v3.0.0"  # contract version stays at 3.0 until breaking changes

# Legacy contract for v1 shim deprecation warnings
LEGACY_CONTRACT_V1 = "v1.x (deprecated, removal in v3.1.0)"
