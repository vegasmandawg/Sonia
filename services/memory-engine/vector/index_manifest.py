"""
Vector Index Manifest (v4.3 Epic B)

Tracks index version, entry count, checksum, and build timestamp.
Used by promotion gates to verify cold-start recall parity.

Manifest format:
{
    "version": 1,
    "entry_count": N,
    "checksum": "sha256:...",
    "built_at": "ISO8601",
    "build_duration_ms": N
}
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("memory-engine.manifest")


class IndexManifest:
    """Manages a manifest file alongside a persisted HNSW index."""

    MANIFEST_VERSION = 1

    def __init__(self, index_path: str):
        """
        Args:
            index_path: Path to the HNSW JSON index file.
                        Manifest is written as <index_path>.manifest.json.
        """
        self._index_path = Path(index_path)
        self._manifest_path = self._index_path.with_suffix(
            self._index_path.suffix + ".manifest.json"
        )

    # ── Write ────────────────────────────────────────────────────────────

    async def write(
        self,
        entry_count: int,
        build_duration_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Compute checksum and write manifest to disk.

        Args:
            entry_count: Number of vectors in the index.
            build_duration_ms: How long the build/backfill took.

        Returns:
            The manifest dict that was written.
        """
        checksum = self._compute_checksum()
        manifest = {
            "version": self.MANIFEST_VERSION,
            "entry_count": entry_count,
            "checksum": checksum,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "build_duration_ms": round(build_duration_ms, 1),
        }

        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info(
            "Manifest written: %d entries, checksum=%s",
            entry_count,
            checksum[:24] + "...",
        )
        return manifest

    # ── Read / Verify ────────────────────────────────────────────────────

    async def read(self) -> Optional[Dict[str, Any]]:
        """Load manifest from disk, or None if missing."""
        if not self._manifest_path.exists():
            return None
        try:
            with open(self._manifest_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Manifest read failed: %s", e)
            return None

    async def verify(self) -> Dict[str, Any]:
        """Verify that the index file matches the manifest checksum.

        Returns:
            {
                "valid": bool,
                "manifest_found": bool,
                "index_found": bool,
                "checksum_match": bool,
                "details": str,
                "manifest": {...} or None,
            }
        """
        result: Dict[str, Any] = {
            "valid": False,
            "manifest_found": False,
            "index_found": self._index_path.exists(),
            "checksum_match": False,
            "details": "",
            "manifest": None,
        }

        if not result["index_found"]:
            result["details"] = "Index file not found"
            return result

        manifest = await self.read()
        if manifest is None:
            result["details"] = "Manifest file not found or unreadable"
            return result

        result["manifest_found"] = True
        result["manifest"] = manifest

        current_checksum = self._compute_checksum()
        stored_checksum = manifest.get("checksum", "")

        if current_checksum == stored_checksum:
            result["checksum_match"] = True
            result["valid"] = True
            result["details"] = "Checksum verified"
        else:
            result["details"] = (
                f"Checksum mismatch: stored={stored_checksum[:24]}... "
                f"current={current_checksum[:24]}..."
            )
            logger.warning(
                "Index checksum mismatch! Stored=%s, Current=%s",
                stored_checksum[:24],
                current_checksum[:24],
            )

        return result

    # ── Internal ─────────────────────────────────────────────────────────

    def _compute_checksum(self) -> str:
        """Compute SHA-256 of the HNSW index file.

        Returns:
            'sha256:<hex>' string, or 'sha256:MISSING' if file absent.
        """
        if not self._index_path.exists():
            return "sha256:MISSING"
        try:
            h = hashlib.sha256()
            with open(self._index_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            return f"sha256:{h.hexdigest()}"
        except Exception as e:
            logger.error("Checksum computation failed: %s", e)
            return f"sha256:ERROR:{e}"
