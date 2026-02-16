"""
Correlation ID trace propagation verifier.

Provides:
- Correlation ID flow verification through pipeline stages
- Cross-service boundary correlation checks
- Orphaned request detection
- Trace completeness scoring
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class TraceStage(Enum):
    INGRESS = "ingress"
    MEMORY_READ = "memory_read"
    MODEL_CALL = "model_call"
    TOOL_EXEC = "tool_exec"
    MEMORY_WRITE = "memory_write"
    RESPONSE = "response"


PIPELINE_STAGES = [s.value for s in TraceStage]

# Regex for correlation ID format: req_xxx or corr_xxx
CORRELATION_ID_PATTERN = re.compile(r"^(req|corr)_[a-zA-Z0-9_-]{4,64}$")


@dataclass
class TraceSpan:
    stage: str
    correlation_id: Optional[str] = None
    service: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceResult:
    correlation_id: str
    stages_present: List[str]
    stages_missing: List[str]
    completeness_score: float  # 0.0 to 1.0
    orphaned: bool = False
    cross_service_valid: bool = True

    def to_dict(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "stages_present": self.stages_present,
            "stages_missing": self.stages_missing,
            "completeness_score": round(self.completeness_score, 4),
            "orphaned": self.orphaned,
            "cross_service_valid": self.cross_service_valid,
        }


@dataclass
class PropagationReport:
    total_requests: int
    complete_traces: int
    incomplete_traces: int
    orphaned_requests: int
    avg_completeness: float
    traces: List[TraceResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "complete_traces": self.complete_traces,
            "incomplete_traces": self.incomplete_traces,
            "orphaned_requests": self.orphaned_requests,
            "avg_completeness": round(self.avg_completeness, 4),
            "traces": [t.to_dict() for t in self.traces[:50]],  # cap output
        }


class TracePropagationVerifier:
    """Verifies correlation ID propagation through the turn pipeline."""

    def __init__(self, expected_stages: Optional[List[str]] = None):
        self.expected_stages = expected_stages or PIPELINE_STAGES
        self._traces: Dict[str, List[TraceSpan]] = {}

    def add_span(self, span: TraceSpan) -> None:
        """Record a trace span."""
        cid = span.correlation_id or "__orphan__"
        if cid not in self._traces:
            self._traces[cid] = []
        self._traces[cid].append(span)

    def ingest_log_entries(self, entries: List[Dict[str, Any]]) -> int:
        """Ingest log entries and extract trace spans."""
        count = 0
        for entry in entries:
            cid = entry.get("correlation_id") or entry.get("request_id")
            stage = entry.get("stage") or entry.get("pipeline_stage")
            service = entry.get("service") or entry.get("source_module")
            ts = entry.get("timestamp")

            span = TraceSpan(
                stage=stage or "unknown",
                correlation_id=cid,
                service=service,
                timestamp=ts,
                metadata={k: v for k, v in entry.items()
                          if k not in ("correlation_id", "request_id", "stage",
                                       "pipeline_stage", "service", "source_module", "timestamp")},
            )
            self.add_span(span)
            count += 1
        return count

    def validate_trace(self, correlation_id: str) -> TraceResult:
        """Validate a single trace for completeness."""
        spans = self._traces.get(correlation_id, [])
        stages_present = list({s.stage for s in spans if s.stage in self.expected_stages})
        stages_missing = [s for s in self.expected_stages if s not in stages_present]
        completeness = len(stages_present) / len(self.expected_stages) if self.expected_stages else 0.0

        # Check cross-service correlation
        services = {s.service for s in spans if s.service}
        cross_service_valid = len(services) <= 1 or all(
            s.correlation_id == correlation_id for s in spans
        )

        # Check for valid correlation ID format
        orphaned = not CORRELATION_ID_PATTERN.match(correlation_id)

        return TraceResult(
            correlation_id=correlation_id,
            stages_present=stages_present,
            stages_missing=stages_missing,
            completeness_score=completeness,
            orphaned=orphaned,
            cross_service_valid=cross_service_valid,
        )

    def validate_all(self) -> PropagationReport:
        """Validate all recorded traces."""
        results: List[TraceResult] = []
        for cid in self._traces:
            results.append(self.validate_trace(cid))

        complete = sum(1 for r in results if r.completeness_score == 1.0)
        incomplete = sum(1 for r in results if 0 < r.completeness_score < 1.0)
        orphaned = sum(1 for r in results if r.orphaned)
        avg = sum(r.completeness_score for r in results) / len(results) if results else 0.0

        return PropagationReport(
            total_requests=len(results),
            complete_traces=complete,
            incomplete_traces=incomplete,
            orphaned_requests=orphaned,
            avg_completeness=avg,
            traces=results,
        )

    def detect_orphans(self) -> List[str]:
        """Return correlation IDs that don't match expected format."""
        orphans = []
        for cid in self._traces:
            if not CORRELATION_ID_PATTERN.match(cid):
                orphans.append(cid)
        return orphans

    def is_valid_correlation_id(self, cid: str) -> bool:
        """Check if a correlation ID matches expected format."""
        return bool(CORRELATION_ID_PATTERN.match(cid))

    def get_summary(self) -> dict:
        """Return verifier summary."""
        report = self.validate_all()
        return {
            "total_traces": report.total_requests,
            "complete": report.complete_traces,
            "incomplete": report.incomplete_traces,
            "orphaned": report.orphaned_requests,
            "avg_completeness": report.avg_completeness,
        }

    def clear(self) -> None:
        """Clear all recorded traces."""
        self._traces.clear()
