"""Canonical version string for the entire SONIA stack.

Import this in every service's main.py to ensure version consistency.

Usage:
    from shared.version import SONIA_VERSION
    app = FastAPI(..., version=SONIA_VERSION)
"""

SONIA_VERSION = "2.9.0"
SONIA_CONTRACT = "v2.9.0"
