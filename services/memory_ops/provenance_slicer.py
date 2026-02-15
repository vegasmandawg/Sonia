"""Provenance slicing and retrieval traceability (v3.3 Epic A).

Provides "why was this retrieved?" query paths and chain extraction
from the governance provenance log.

Features:
    - Slice by time window (sequence range)
    - Slice by memory type
    - Slice by actor/source
    - Evidence chain extraction for a specific proposal
    - Deterministic ordering for identical query inputs
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .provenance import GovernanceProvenance, GovernanceRecord


@dataclass(frozen=True)
class ProvenanceSlice:
    """Result of a provenance query with deterministic ordering."""
    query_type: str
    query_params: Dict[str, Any]
    records: tuple  # tuple of GovernanceRecord for immutability
    record_count: int
    slice_hash: str  # deterministic hash of this slice


class ProvenanceSlicer:
    """Query interface for governance provenance chains."""

    def __init__(self, provenance: GovernanceProvenance):
        self._provenance = provenance

    def _make_slice(
        self,
        query_type: str,
        query_params: Dict[str, Any],
        records: List[GovernanceRecord],
    ) -> ProvenanceSlice:
        """Create a deterministic slice from filtered records."""
        # Sort by seq for deterministic ordering
        sorted_records = sorted(records, key=lambda r: r.seq)
        chain = [
            {"seq": r.seq, "record_type": r.record_type,
             "proposal_id": r.proposal_id}
            for r in sorted_records
        ]
        canonical = json.dumps(chain, sort_keys=True, separators=(",", ":"))
        slice_hash = hashlib.sha256(canonical.encode()).hexdigest()

        return ProvenanceSlice(
            query_type=query_type,
            query_params=query_params,
            records=tuple(sorted_records),
            record_count=len(sorted_records),
            slice_hash=slice_hash,
        )

    def by_sequence_window(
        self, seq_start: int, seq_end: int,
    ) -> ProvenanceSlice:
        """Slice provenance by sequence range [start, end)."""
        filtered = [
            r for r in self._provenance.records
            if seq_start <= r.seq < seq_end
        ]
        return self._make_slice(
            "sequence_window",
            {"seq_start": seq_start, "seq_end": seq_end},
            filtered,
        )

    def by_memory_type(self, memory_type: str) -> ProvenanceSlice:
        """Slice provenance for a specific memory type."""
        filtered = [
            r for r in self._provenance.records
            if r.record_type == "proposal_created"
               and r.details.get("memory_type") == memory_type
        ]
        return self._make_slice(
            "memory_type",
            {"memory_type": memory_type},
            filtered,
        )

    def by_proposal_id(self, proposal_id: str) -> ProvenanceSlice:
        """Extract the full evidence chain for a specific proposal."""
        filtered = [
            r for r in self._provenance.records
            if r.proposal_id == proposal_id
        ]
        return self._make_slice(
            "proposal_chain",
            {"proposal_id": proposal_id},
            filtered,
        )

    def by_session_id(self, session_id: str) -> ProvenanceSlice:
        """Slice provenance for a specific session."""
        filtered = [
            r for r in self._provenance.records
            if r.session_id == session_id
        ]
        return self._make_slice(
            "session",
            {"session_id": session_id},
            filtered,
        )

    def by_record_type(self, record_type: str) -> ProvenanceSlice:
        """Slice provenance for a specific record type."""
        filtered = [
            r for r in self._provenance.records
            if r.record_type == record_type
        ]
        return self._make_slice(
            "record_type",
            {"record_type": record_type},
            filtered,
        )

    def why_retrieved(self, proposal_id: str) -> Dict[str, Any]:
        """Answer 'why was this retrieved?' for a proposal.

        Returns the evidence chain: creation -> classification -> conflicts ->
        approval/rejection -> application, with reason codes at each step.
        """
        chain = self.by_proposal_id(proposal_id)
        if chain.record_count == 0:
            return {
                "proposal_id": proposal_id,
                "has_provenance": False,
                "chain": [],
            }

        steps = []
        for rec in chain.records:
            steps.append({
                "seq": rec.seq,
                "step": rec.record_type,
                "decision": rec.decision,
                "reason": rec.reason_code,
            })

        return {
            "proposal_id": proposal_id,
            "has_provenance": True,
            "chain": steps,
            "chain_hash": chain.slice_hash,
        }
