"""Canonical path constants for the entire SONIA stack.

All services MUST use these constants instead of hardcoding paths.
Root contract: every writable path must be under CANONICAL_ROOT (S:\\).
"""

import os
import sys
from pathlib import Path


# ============================================================================
# Root Contract
# ============================================================================

CANONICAL_ROOT = Path(os.getenv("SONIA_ROOT", "S:\\")).resolve()

# ============================================================================
# Standard Directories
# ============================================================================

LOGS_DIR = CANONICAL_ROOT / "logs"
LOGS_SERVICES_DIR = LOGS_DIR / "services"
LOGS_GATEWAY_DIR = LOGS_DIR / "gateway"

STATE_DIR = CANONICAL_ROOT / "state"
PIDS_DIR = STATE_DIR / "pids"

DATA_DIR = CANONICAL_ROOT / "data"
MEMORY_DB_DIR = DATA_DIR / "memory"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
SESSIONS_DIR = DATA_DIR / "sessions"

CONFIG_DIR = CANONICAL_ROOT / "config"
REPORTS_DIR = CANONICAL_ROOT / "reports"
RELEASES_DIR = CANONICAL_ROOT / "releases"
QUARANTINE_DIR = CANONICAL_ROOT / "quarantine"
BACKUPS_DIR = CANONICAL_ROOT / "backups"
TMP_DIR = CANONICAL_ROOT / "tmp"
AUDIT_DIR = CANONICAL_ROOT / "audit"

# ============================================================================
# Path Security
# ============================================================================

_BLOCKED_PREFIXES = {"\\\\"}  # UNC paths


def is_safe_path(path: str) -> bool:
    """Check if a path is within the SONIA root contract.

    Blocks:
    - Paths outside CANONICAL_ROOT
    - UNC network paths (\\\\server\\share)
    - Symlinks that resolve outside root
    - Paths with .. traversal (handled by resolve())
    """
    if not path:
        return False

    # Block UNC paths
    if path.startswith("\\\\") or path.startswith("//"):
        return False

    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False

    # Block symlinks that escape root
    raw = Path(path)
    if raw.exists() and raw.is_symlink():
        link_target = raw.resolve()
        if not str(link_target).startswith(str(CANONICAL_ROOT)):
            return False

    # Must be under canonical root
    return str(resolved).startswith(str(CANONICAL_ROOT))


def sanitize_path(path: str) -> Path:
    """Sanitize and validate a path, raising ValueError if unsafe.

    Returns the resolved Path if valid.
    """
    if not is_safe_path(path):
        raise ValueError(f"Path violates root contract (must be under {CANONICAL_ROOT}): {path}")
    return Path(path).resolve()


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_path_join(base: Path, *parts: str) -> Path:
    """Safely join path components, preventing traversal escapes.

    Raises ValueError if the result would escape the base directory.
    """
    joined = base
    for part in parts:
        # Strip leading separators and .. to prevent traversal
        clean = part.lstrip("/\\")
        if ".." in clean.split(os.sep) or ".." in clean.split("/"):
            raise ValueError(f"Path traversal blocked: {part}")
        joined = joined / clean

    resolved = joined.resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path escapes base {base}: {joined}")
    return resolved


# ============================================================================
# Long-path support (Windows)
# ============================================================================

def long_path(path: str) -> str:
    """Add Windows long-path prefix if needed (>240 chars)."""
    if sys.platform == "win32" and len(path) > 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path
