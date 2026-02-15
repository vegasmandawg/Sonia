"""Ledger export/import with integrity verification (v3.3 Epic A).

Supports exporting governance state (proposals + provenance + conflicts)
to a portable format and re-importing with hash verification.

Invariants:
    - Export produces deterministic output for same input.
    - Import verifies integrity via hash comparison.
    - No silent data loss during roundtrip.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .governance_pipeline import MemoryGovernancePipeline
from .provenance import GovernanceProvenance


@dataclass(frozen=True)
class ExportBundle:
    """Portable governance state bundle with integrity hash."""
    version: str
    proposal_count: int
    provenance_count: int
    conflict_count: int
    provenance_hash: str
    data: Dict[str, Any]
    bundle_hash: str


class LedgerExporter:
    """Export governance state to portable format."""

    def __init__(self, pipeline: MemoryGovernancePipeline):
        self._pipeline = pipeline

    def export_bundle(self) -> ExportBundle:
        """Export full governance state as a portable bundle."""
        proposals = []
        for pid, p in self._pipeline.queue._proposals.items():
            proposals.append({
                "proposal_id": p.proposal_id,
                "session_id": p.session_id,
                "memory_type": p.memory_type.value,
                "subject_key": p.subject_key,
                "payload_hash": p.payload_hash,
                "state": p.state.value,
                "schema_version": p.schema_version,
                "policy_version": p.policy_version,
                "confidence": p.confidence,
                "risk_tier": p.risk_tier.value,
                "created_seq": p.created_seq,
            })

        provenance = []
        for rec in self._pipeline.provenance.records:
            provenance.append({
                "seq": rec.seq,
                "record_type": rec.record_type,
                "proposal_id": rec.proposal_id,
                "session_id": rec.session_id,
                "decision": rec.decision,
                "reason_code": rec.reason_code,
            })

        conflicts = []
        for c in self._pipeline.conflicts.conflicts:
            conflicts.append({
                "conflict_id": c.conflict_id,
                "conflict_type": c.conflict_type,
                "proposal_id_a": c.proposal_id_a,
                "proposal_id_b": c.proposal_id_b,
                "subject_key": c.subject_key,
                "resolution": c.resolution,
            })

        data = {
            "proposals": proposals,
            "provenance": provenance,
            "conflicts": conflicts,
        }

        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        bundle_hash = hashlib.sha256(canonical.encode()).hexdigest()

        return ExportBundle(
            version="3.3.0",
            proposal_count=len(proposals),
            provenance_count=len(provenance),
            conflict_count=len(conflicts),
            provenance_hash=self._pipeline.provenance.deterministic_hash(),
            data=data,
            bundle_hash=bundle_hash,
        )


class LedgerImporter:
    """Import and verify governance state bundles."""

    @staticmethod
    def verify_bundle(bundle: ExportBundle) -> Dict[str, Any]:
        """Verify bundle integrity via hash comparison."""
        canonical = json.dumps(
            bundle.data, sort_keys=True, separators=(",", ":"),
        )
        computed_hash = hashlib.sha256(canonical.encode()).hexdigest()
        match = computed_hash == bundle.bundle_hash

        return {
            "valid": match,
            "expected_hash": bundle.bundle_hash,
            "computed_hash": computed_hash,
            "proposal_count": bundle.proposal_count,
            "provenance_count": bundle.provenance_count,
            "conflict_count": bundle.conflict_count,
        }
