"""
Dataset Manifest Schema -- v2.6 Track A (production-hardened)

Strict manifest contract for dataset generation. Every build is reproducible
from a manifest + inputs. Fails early on unknown keys, missing provenance,
or integrity mismatches.

Schema version: 1.1.0
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


SCHEMA_VERSION = "1.1.0"

# Required top-level keys (strict mode rejects anything else)
_REQUIRED_KEYS = {
    "name", "version", "source", "license", "schema_version",
    "created_at", "description", "provenance",
}
_OPTIONAL_KEYS = {
    "filters", "tags", "files", "split_config", "invariant_config",
    "export_config", "build_id",
}
_ALL_KEYS = _REQUIRED_KEYS | _OPTIONAL_KEYS

_REQUIRED_PROVENANCE_KEYS = {"author", "created_at", "tool_version"}
_OPTIONAL_PROVENANCE_KEYS = {"source_urls", "notes", "parent_manifest"}


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class ManifestValidationError(Exception):
    """Raised when manifest fails strict validation."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Manifest validation failed ({len(errors)} error(s)):\n" +
                         "\n".join(f"  - {e}" for e in errors))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    """Single file tracked by a manifest."""
    relative_path: str
    sha256: str
    size_bytes: int
    line_count: Optional[int] = None


@dataclass
class SplitConfig:
    """Train/val/test split configuration."""
    train_ratio: float = 0.85
    val_ratio: float = 0.10
    test_ratio: float = 0.05
    seed: int = 42
    stratify_by: str = "category"
    min_per_class: int = 1

    def validate(self) -> List[str]:
        errors: List[str] = []
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            errors.append(f"Split ratios sum to {total:.6f}, expected 1.0")
        for name, val in [("train", self.train_ratio), ("val", self.val_ratio), ("test", self.test_ratio)]:
            if val < 0.0 or val > 1.0:
                errors.append(f"Split ratio '{name}' = {val} out of [0, 1] range")
        if self.min_per_class < 0:
            errors.append(f"min_per_class must be >= 0, got {self.min_per_class}")
        return errors


@dataclass
class InvariantConfig:
    """Identity invariant enforcement configuration."""
    mode: str = "enforce"  # "audit" or "enforce"
    severity_thresholds: Dict[str, int] = field(default_factory=lambda: {
        "CRITICAL": 0,  # zero tolerance
        "MAJOR": 5,     # up to 5 before fail
        "MINOR": -1,    # unlimited (warn only)
    })
    anchor_patterns: List[str] = field(default_factory=list)
    scan_roles: List[str] = field(default_factory=lambda: ["assistant"])

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.mode not in ("audit", "enforce"):
            errors.append(f"invariant_config.mode must be 'audit' or 'enforce', got '{self.mode}'")
        return errors


@dataclass
class ExportConfig:
    """JSONL export configuration."""
    format: str = "jsonl"
    include_metadata: bool = False
    sort_keys: bool = True
    ensure_ascii: bool = False

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.format not in ("jsonl",):
            errors.append(f"export_config.format must be 'jsonl', got '{self.format}'")
        return errors


@dataclass
class Provenance:
    """Build provenance metadata."""
    author: str
    created_at: str
    tool_version: str
    source_urls: List[str] = field(default_factory=list)
    notes: str = ""
    parent_manifest: str = ""

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.author.strip():
            errors.append("provenance.author is required")
        if not self.created_at.strip():
            errors.append("provenance.created_at is required")
        if not self.tool_version.strip():
            errors.append("provenance.tool_version is required")
        return errors


@dataclass
class DatasetManifest:
    """Top-level manifest for a dataset partition (strict mode)."""
    name: str
    version: str
    source: str
    license: str
    provenance: Provenance
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""
    build_id: str = ""
    filters: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    files: List[FileEntry] = field(default_factory=list)
    split_config: Optional[SplitConfig] = None
    invariant_config: Optional[InvariantConfig] = None
    export_config: Optional[ExportConfig] = None

    # ---- validation ------------------------------------------------------

    def validate(self, strict: bool = True) -> List[str]:
        """Full validation. Returns list of error strings (empty = valid)."""
        errors: List[str] = []

        # Required fields
        if not self.name.strip():
            errors.append("name is required")
        if not self.version.strip():
            errors.append("version is required")
        if not self.source.strip():
            errors.append("source is required")
        if not self.license.strip():
            errors.append("license is required")

        # Provenance
        errors.extend(self.provenance.validate())

        # Sub-config validation
        if self.split_config:
            errors.extend(self.split_config.validate())
        if self.invariant_config:
            errors.extend(self.invariant_config.validate())
        if self.export_config:
            errors.extend(self.export_config.validate())

        return errors

    def validate_or_raise(self, strict: bool = True) -> None:
        """Validate and raise ManifestValidationError if invalid."""
        errors = self.validate(strict=strict)
        if errors:
            raise ManifestValidationError(errors)

    # ---- deterministic build ID ------------------------------------------

    def compute_build_id(self, config_hash: str = "") -> str:
        """
        Deterministic build ID from manifest hash + source hashes + config hash.
        Same inputs always produce the same build ID.
        """
        h = hashlib.sha256()
        # Manifest identity
        h.update(f"{self.name}:{self.version}:{self.schema_version}".encode())
        # Source file hashes (sorted for determinism)
        for fe in sorted(self.files, key=lambda f: f.relative_path):
            h.update(f"{fe.relative_path}:{fe.sha256}".encode())
        # Config hash
        if config_hash:
            h.update(config_hash.encode())
        # Split config (affects output)
        if self.split_config:
            sc = self.split_config
            h.update(f"split:{sc.train_ratio}:{sc.val_ratio}:{sc.test_ratio}:{sc.seed}".encode())
        self.build_id = h.hexdigest()[:16]
        return self.build_id

    # ---- file management -------------------------------------------------

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

    def scan_directory(
        self, base_dir: Path,
        extensions: tuple = (".jsonl", ".json", ".txt", ".md"),
    ) -> int:
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
        d = {}
        d["name"] = self.name
        d["version"] = self.version
        d["source"] = self.source
        d["license"] = self.license
        d["schema_version"] = self.schema_version
        d["created_at"] = self.created_at
        d["description"] = self.description
        d["build_id"] = self.build_id
        d["provenance"] = asdict(self.provenance)
        d["filters"] = self.filters
        d["tags"] = self.tags
        d["files"] = [asdict(f) for f in self.files]
        if self.split_config:
            d["split_config"] = asdict(self.split_config)
        if self.invariant_config:
            d["invariant_config"] = asdict(self.invariant_config)
        if self.export_config:
            d["export_config"] = asdict(self.export_config)
        return d

    def save(self, path: Path) -> None:
        self.validate_or_raise()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False, sort_keys=True)

    @classmethod
    def load(cls, path: Path) -> "DatasetManifest":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "DatasetManifest":
        """Reconstruct manifest from dict with strict key checking."""
        # Validate keys
        known = _ALL_KEYS
        unknown = set(data.keys()) - known
        if unknown:
            raise ManifestValidationError([f"Unknown key(s): {', '.join(sorted(unknown))}"])

        files = [FileEntry(**fe) for fe in data.pop("files", [])]
        prov_data = data.pop("provenance", {})
        # Strict provenance key check
        prov_unknown = set(prov_data.keys()) - _REQUIRED_PROVENANCE_KEYS - _OPTIONAL_PROVENANCE_KEYS
        if prov_unknown:
            raise ManifestValidationError([f"Unknown provenance key(s): {', '.join(sorted(prov_unknown))}"])
        provenance = Provenance(**prov_data)

        split_data = data.pop("split_config", None)
        split_config = SplitConfig(**split_data) if split_data else None

        inv_data = data.pop("invariant_config", None)
        invariant_config = InvariantConfig(**inv_data) if inv_data else None

        exp_data = data.pop("export_config", None)
        export_config = ExportConfig(**exp_data) if exp_data else None

        return cls(
            files=files,
            provenance=provenance,
            split_config=split_config,
            invariant_config=invariant_config,
            export_config=export_config,
            **data,
        )

    # ---- verification ----------------------------------------------------

    def verify(self, base_dir: Path) -> List[str]:
        """Return list of integrity errors (empty = all good)."""
        errors: List[str] = []
        for fe in self.files:
            full = base_dir / fe.relative_path
            if not full.exists():
                errors.append(f"MISSING: {fe.relative_path}")
                continue
            actual = _sha256(full)
            if actual != fe.sha256:
                errors.append(
                    f"HASH_MISMATCH: {fe.relative_path} "
                    f"expected={fe.sha256[:12]}... got={actual[:12]}..."
                )
        return errors


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

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
