"""Canonical version string for the entire SONIA stack.

Import this in every service's main.py to ensure version consistency.

Usage:
    from shared.version import SONIA_VERSION, SONIA_CONTRACT
    app = FastAPI(..., version=SONIA_VERSION)
"""

SONIA_VERSION = "4.4.0-dev"
SONIA_CONTRACT = "v4.3.0"  # contract pin unchanged until v4.4 scope is locked

# Legacy contract for v1 shim deprecation warnings
LEGACY_CONTRACT_V1 = "v1.x (deprecated, removal in v3.1.0)"
