"""
Reproducible build policy: frozen dependencies and lock hash verification.

Ensures all dependencies are fully pinned (no floating ranges) and
that dependency lock files have verifiable SHA-256 hashes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DependencyEntry:
    """A single dependency with version pin."""
    name: str
    version: str          # exact version, e.g. "1.2.3"
    version_spec: str     # original spec, e.g. "==1.2.3" or ">=1.2"
    sha256: Optional[str] = None

    def is_fully_pinned(self) -> bool:
        """Check if version spec uses exact pinning (== only)."""
        return self.version_spec.startswith("==") and not any(
            c in self.version_spec for c in (">", "<", "~", "!", "*")
        )


class UnpinnedDependencyError(Exception):
    pass


class LockHashMismatchError(Exception):
    pass


class FrozenDependencySet:
    """Registry of frozen dependencies with pinning enforcement."""

    def __init__(self):
        self._deps: Dict[str, DependencyEntry] = {}

    def add(self, dep: DependencyEntry) -> None:
        self._deps[dep.name] = dep

    def get(self, name: str) -> Optional[DependencyEntry]:
        return self._deps.get(name)

    def list_all(self) -> List[DependencyEntry]:
        return sorted(self._deps.values(), key=lambda d: d.name)

    def unpinned_deps(self) -> List[str]:
        """Return names of deps with floating version ranges."""
        return sorted(
            d.name for d in self._deps.values() if not d.is_fully_pinned()
        )

    def all_pinned(self) -> bool:
        return len(self.unpinned_deps()) == 0

    def compute_lock_hash(self) -> str:
        """Compute deterministic hash over all deps (sorted by name)."""
        entries = []
        for d in sorted(self._deps.values(), key=lambda x: x.name):
            entries.append(f"{d.name}|{d.version_spec}|{d.sha256 or 'none'}")
        canonical = "\n".join(entries)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def verify_lock_hash(self, expected_hash: str) -> bool:
        return self.compute_lock_hash() == expected_hash

    def export_lock(self) -> dict:
        return {
            "dep_count": len(self._deps),
            "all_pinned": self.all_pinned(),
            "lock_hash": self.compute_lock_hash(),
            "entries": [
                {"name": d.name, "version_spec": d.version_spec, "sha256": d.sha256}
                for d in sorted(self._deps.values(), key=lambda x: x.name)
            ],
        }


def parse_requirements_line(line: str) -> Optional[DependencyEntry]:
    """Parse a requirements.txt line into a DependencyEntry."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    # Match: name==version or name>=version etc.
    m = re.match(r'^([A-Za-z0-9_.-]+)\s*([><=!~]+.+)$', line)
    if m:
        name, spec = m.group(1), m.group(2).strip()
        version = re.sub(r'^[><=!~]+', '', spec).strip()
        return DependencyEntry(name=name, version=version, version_spec=spec)
    return None
