"""
Dataset Manifest Schema — v2.6 Track A

Every dataset under S:\datasets gets a manifest describing its origin,
version, license, schema version, content filters, and integrity hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


SCHEMA_VERSION = "1.0.0"


@dataclass
class FileEntry:
    """Single file tracked by a manifest."""
    relative_path: str
    sha256: str
    size_bytes: int
    line_count: Optional[int] = None


@dataclass
class DatasetManifest:
    """Top-level manifest for a dataset partition."""
    name: str
    version: str
    source: str
    license: str
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""
    filters: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    files: List[FileEntry] = field(default_factory=list)

    # ---- builders --------------------------------------------------------

    def add_file(self, base_dir: Path, rel_path: str) -> FileEntry:
        """Hash a file and add it to the manifest."""
        full = base_dir / rel_path
        sha = _sha256(full)
        size = full.stat().st_size
        lines = _count_lines(full)
        entry = FileEntry(
            relative_path=rel_path,
            sha256=sha,
            size_bytes=size,
            line_count=lines,
        )
        self.files.append(entry)
        return entry

    def scan_directory(self, base_dir: Path, extensions: tuple[str, ...] = (".jsonl", ".json", ".txt", ".md")) -> int:
        """Walk base_dir, hash every matching file, return count added."""
        count = 0
        for root, _dirs, filenames in os.walk(base_dir):
            for fn in sorted(filenames):
                if fn.lower().endswith(extensions):
                    rel = os.path.relpath(os.path.join(root, fn), base_dir)
                    self.add_file(base_dir, rel)
                    count += 1
        return count

    # ---- serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "DatasetManifest":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        files = [FileEntry(**fe) for fe in data.pop("files", [])]
        return cls(**data, files=files)

    # ---- verification ----------------------------------------------------

    def verify(self, base_dir: Path) -> list[str]:
        """Return list of integrity errors (empty = all good)."""
        errors: list[str] = []
        for fe in self.files:
            full = base_dir / fe.relative_path
            if not full.exists():
                errors.append(f"MISSING: {fe.relative_path}")
                continue
            actual = _sha256(full)
            if actual != fe.sha256:
                errors.append(f"HASH_MISMATCH: {fe.relative_path} expected={fe.sha256[:12]}... got={actual[:12]}...")
        return errors


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_lines(path: Path) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return None
