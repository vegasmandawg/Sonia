"""Redaction Lineage Policy — v4.2 E1.

Enforces immutable redaction lineage: once a redaction is applied,
the chain of redactions is append-only with tamper detection via
SHA-256 chain hashing.
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class RedactionRecord:
    """Immutable record of a redaction event."""
    redaction_id: str
    entry_id: str
    redacted_fields: tuple  # tuple of field names
    reason: str
    performed_by: str
    timestamp: str  # ISO timestamp
    previous_hash: str  # hash of previous record in chain (empty for first)

    def __post_init__(self):
        if not self.redaction_id:
            raise ValueError("redaction_id must be non-empty")
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if not self.performed_by:
            raise ValueError("performed_by must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "redaction_id": self.redaction_id,
            "entry_id": self.entry_id,
            "redacted_fields": list(self.redacted_fields),
            "reason": self.reason,
            "performed_by": self.performed_by,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class RedactionLineageChain:
    """Append-only redaction chain with tamper detection.

    The chain is ordered by insertion. Each record's previous_hash
    must match the fingerprint of the preceding record (or be empty
    for the first record). Tamper detection verifies this invariant.
    """

    def __init__(self):
        self._records: List[RedactionRecord] = []
        self._by_entry: Dict[str, List[RedactionRecord]] = {}

    def append(self, record: RedactionRecord) -> None:
        """Append a redaction record to the chain.

        Validates that previous_hash matches the last record's fingerprint.
        """
        if self._records:
            expected_prev = self._records[-1].fingerprint
            if record.previous_hash != expected_prev:
                raise ValueError(
                    f"Chain integrity violation: expected previous_hash "
                    f"{expected_prev[:16]}..., got {record.previous_hash[:16]}..."
                )
        else:
            if record.previous_hash != "":
                raise ValueError(
                    "First record in chain must have empty previous_hash"
                )

        self._records.append(record)
        if record.entry_id not in self._by_entry:
            self._by_entry[record.entry_id] = []
        self._by_entry[record.entry_id].append(record)

    def verify_chain_integrity(self) -> dict:
        """Verify the entire chain is tamper-free.

        Returns dict with 'valid' (bool), 'length' (int), 'broken_at' (int or None).
        """
        if not self._records:
            return {"valid": True, "length": 0, "broken_at": None}

        # First record must have empty previous_hash
        if self._records[0].previous_hash != "":
            return {"valid": False, "length": len(self._records), "broken_at": 0}

        for i in range(1, len(self._records)):
            expected = self._records[i - 1].fingerprint
            if self._records[i].previous_hash != expected:
                return {"valid": False, "length": len(self._records), "broken_at": i}

        return {"valid": True, "length": len(self._records), "broken_at": None}

    def get_redactions_for_entry(self, entry_id: str) -> List[RedactionRecord]:
        """Get all redactions applied to a specific entry."""
        return list(self._by_entry.get(entry_id, []))

    def chain_hash(self) -> str:
        """Compute a hash of the entire chain for comparison."""
        if not self._records:
            return hashlib.sha256(b"empty_chain").hexdigest()
        # Hash of all fingerprints concatenated
        combined = "".join(r.fingerprint for r in self._records)
        return hashlib.sha256(combined.encode()).hexdigest()

    @property
    def length(self) -> int:
        return len(self._records)

    @property
    def records(self) -> List[RedactionRecord]:
        return list(self._records)

    def is_immutable_after(self, index: int) -> bool:
        """Check that records at or before index have not been modified.

        This is verified by re-checking the chain integrity up to that index.
        """
        for i in range(min(index + 1, len(self._records))):
            if i == 0:
                if self._records[i].previous_hash != "":
                    return False
            else:
                expected = self._records[i - 1].fingerprint
                if self._records[i].previous_hash != expected:
                    return False
        return True
