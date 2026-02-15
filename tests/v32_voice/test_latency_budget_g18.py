"""G18 latency budget validation tests.

Test 14: Verify p95 warm-path latency stays under threshold using
fixture data. Uses event-native timestamps (not stopwatch glue).

G18 threshold: p95 <= 1200 ms warm-path
(speech detected -> first assistant output)
"""
import pytest

from services.pipecat.voice.turn_events import TurnEvent
from services.pipecat.voice.turn_router import TurnRouter
from services.pipecat.voice.latency_metrics import LatencyCollector

# ── Helpers ──────────────────────────────────────────────────────────────

SID = "latency-session"
CID = "corr-latency"
MS = 1_000_000  # 1ms in nanoseconds


def _evt(event_type, seq, turn_id, ts_ns):
    return TurnEvent(
        event_type=event_type,
        session_id=SID,
        turn_id=turn_id,
        seq=seq,
        ts_monotonic_ns=ts_ns,
        correlation_id=CID,
    )


def _run_turn(router, turn_id, detect_offset_ms, first_emit_offset_ms):
    """Simulate a full turn with known latency.

    detect_offset_ms: time of TURN_STARTED from t=0
    first_emit_offset_ms: time of MODEL_FIRST_TOKEN from t=0
    Warm path = first_emit - detect.
    """
    base_ns = 0
    router.start_turn(SID, turn_id, CID)

    events = [
        _evt("TURN_STARTED", 1, turn_id, base_ns + detect_offset_ms * MS),
        _evt("ASR_FINAL", 2, turn_id, base_ns + (detect_offset_ms + 50) * MS),
        _evt("MODEL_FIRST_TOKEN", 3, turn_id, base_ns + first_emit_offset_ms * MS),
        _evt("TTS_STARTED", 4, turn_id, base_ns + (first_emit_offset_ms + 10) * MS),
        _evt("TTS_ENDED", 5, turn_id, base_ns + (first_emit_offset_ms + 500) * MS),
    ]
    for e in events:
        router.ingest(e)


# ── Tests ────────────────────────────────────────────────────────────────

class TestLatencyBudgetG18:

    def test_g18_latency_budget_p95_under_threshold_fixture(self):
        """Test 14: Fixture data with known latencies meets G18 p95 <= 1200ms.

        20 turns with warm-path latencies from 200ms to 1100ms.
        p95 should be around 1050ms, well under 1200ms threshold.
        """
        router = TurnRouter()

        # 20 turns: warm-path latencies spread from 200ms to 1100ms
        latencies_ms = [
            200, 300, 350, 400, 450, 500, 550, 600, 650, 700,
            750, 800, 850, 900, 950, 1000, 1050, 1050, 1100, 1100,
        ]
        for i, lat_ms in enumerate(latencies_ms):
            turn_id = f"turn-{i:03d}"
            detect_ms = 100  # fixed detect time
            first_emit_ms = 100 + lat_ms
            _run_turn(router, turn_id, detect_ms, first_emit_ms)

        stats = router.latency.compute_percentiles()
        assert stats["count"] == 20
        assert stats["p95_ms"] is not None
        assert stats["p95_ms"] <= LatencyCollector.G18_P95_THRESHOLD_MS, (
            f"G18 FAIL: p95={stats['p95_ms']}ms > threshold={LatencyCollector.G18_P95_THRESHOLD_MS}ms"
        )
        assert stats["g18_pass"] is True

    def test_g18_fails_when_p95_exceeds_threshold(self):
        """Verify G18 correctly reports failure when p95 > 1200ms."""
        router = TurnRouter()

        # 20 turns: most are slow (1500ms+)
        for i in range(20):
            turn_id = f"slow-{i:03d}"
            _run_turn(router, turn_id, 100, 100 + 1500)

        stats = router.latency.compute_percentiles()
        assert stats["p95_ms"] > LatencyCollector.G18_P95_THRESHOLD_MS
        assert stats["g18_pass"] is False

    def test_latency_collector_records_only_first_emit(self):
        """First emit timestamp is locked -- subsequent emits don't overwrite."""
        collector = LatencyCollector()
        collector.record_turn_start(SID, "t1", 100 * MS)
        collector.record_first_emit(SID, "t1", 300 * MS)
        collector.record_first_emit(SID, "t1", 999 * MS)  # should be ignored
        rec = collector.finalize_turn(SID, "t1")
        assert rec.warm_path_ms == 200.0  # 300-100, not 999-100

    def test_latency_collector_pending_and_finalized(self):
        """Pending count decrements and finalized count increments on finalize."""
        collector = LatencyCollector()
        collector.record_turn_start(SID, "t1", 100 * MS)
        assert collector.pending_count == 1
        assert collector.finalized_count == 0

        collector.record_first_emit(SID, "t1", 300 * MS)
        collector.finalize_turn(SID, "t1")
        assert collector.pending_count == 0
        assert collector.finalized_count == 1
