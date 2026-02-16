"""
Unit tests for trace_propagation.py — TracePropagationVerifier.

Covers:
- Span recording
- Complete trace validation
- Incomplete trace detection
- Orphaned request detection
- Log entry ingestion
- Cross-service correlation
- Summary and report
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"S:\services\api-gateway")

from trace_propagation import (
    TracePropagationVerifier,
    TraceSpan,
    TraceStage,
    PropagationReport,
    PIPELINE_STAGES,
    CORRELATION_ID_PATTERN,
)


def _complete_trace(cid: str = "req_abc123") -> list:
    """Return spans for a complete trace."""
    return [
        TraceSpan(stage=s, correlation_id=cid, service="api-gateway")
        for s in PIPELINE_STAGES
    ]


class TestTracePropagationVerifier:
    """Tests for TracePropagationVerifier."""

    def test_add_span(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id="req_001"))
        assert len(v._traces) == 1

    def test_complete_trace_score_1(self):
        v = TracePropagationVerifier()
        for span in _complete_trace():
            v.add_span(span)
        result = v.validate_trace("req_abc123")
        assert result.completeness_score == 1.0
        assert len(result.stages_missing) == 0

    def test_incomplete_trace(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id="req_002"))
        v.add_span(TraceSpan(stage="response", correlation_id="req_002"))
        result = v.validate_trace("req_002")
        assert result.completeness_score < 1.0
        assert len(result.stages_missing) > 0

    def test_orphaned_request_detected(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id="bad_format"))
        result = v.validate_trace("bad_format")
        assert result.orphaned is True

    def test_valid_correlation_id(self):
        v = TracePropagationVerifier()
        assert v.is_valid_correlation_id("req_abc123")
        assert v.is_valid_correlation_id("corr_test_xyz")
        assert not v.is_valid_correlation_id("bad_format")
        assert not v.is_valid_correlation_id("")

    def test_detect_orphans(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id="req_good"))
        v.add_span(TraceSpan(stage="ingress", correlation_id="__orphan__"))
        v.add_span(TraceSpan(stage="ingress", correlation_id="no_prefix"))
        orphans = v.detect_orphans()
        assert "__orphan__" in orphans
        assert "no_prefix" in orphans
        assert "req_good" not in orphans

    def test_ingest_log_entries(self):
        v = TracePropagationVerifier()
        entries = [
            {"correlation_id": "req_log1", "stage": "ingress", "service": "gateway"},
            {"correlation_id": "req_log1", "stage": "model_call", "service": "router"},
            {"request_id": "req_log2", "pipeline_stage": "response", "source_module": "gateway"},
        ]
        count = v.ingest_log_entries(entries)
        assert count == 3
        assert "req_log1" in v._traces
        assert "req_log2" in v._traces

    def test_validate_all_report(self):
        v = TracePropagationVerifier()
        for span in _complete_trace("req_full"):
            v.add_span(span)
        v.add_span(TraceSpan(stage="ingress", correlation_id="req_partial"))

        report = v.validate_all()
        assert report.total_requests == 2
        assert report.complete_traces == 1
        assert report.avg_completeness > 0

    def test_report_to_dict(self):
        v = TracePropagationVerifier()
        for span in _complete_trace():
            v.add_span(span)
        report = v.validate_all()
        d = report.to_dict()
        assert "total_requests" in d
        assert "avg_completeness" in d
        assert "traces" in d

    def test_trace_result_to_dict(self):
        v = TracePropagationVerifier()
        for span in _complete_trace():
            v.add_span(span)
        result = v.validate_trace("req_abc123")
        d = result.to_dict()
        assert d["completeness_score"] == 1.0
        assert d["orphaned"] is False

    def test_get_summary(self):
        v = TracePropagationVerifier()
        for span in _complete_trace():
            v.add_span(span)
        summary = v.get_summary()
        assert summary["total_traces"] == 1
        assert summary["complete"] == 1

    def test_clear(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id="req_x"))
        v.clear()
        assert len(v._traces) == 0

    def test_pipeline_stages_count(self):
        assert len(PIPELINE_STAGES) == 6

    def test_none_correlation_becomes_orphan(self):
        v = TracePropagationVerifier()
        v.add_span(TraceSpan(stage="ingress", correlation_id=None))
        orphans = v.detect_orphans()
        assert "__orphan__" in orphans
