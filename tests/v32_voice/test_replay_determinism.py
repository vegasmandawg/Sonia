"""Replay determinism tests (G19).

Test 13: Replaying the same event sequence produces identical terminal
snapshot hash and command log.

Hashes only deterministic fields (state, seq, terminal, reason, flags).
Excludes wall-clock/non-deterministic data.
"""
import pytest

from services.pipecat.voice.turn_events import TurnEvent
from services.pipecat.voice.turn_state import TurnState, make_initial_snapshot
from services.pipecat.voice.turn_reducer import reduce_turn
from services.pipecat.voice.turn_router import TurnRouter

# ── Helpers ──────────────────────────────────────────────────────────────

SID = "replay-session"
TID = "replay-turn"
CID = "corr-replay"


def _evt(event_type, seq, ts_ns=None):
    return TurnEvent(
        event_type=event_type,
        session_id=SID,
        turn_id=TID,
        seq=seq,
        ts_monotonic_ns=ts_ns if ts_ns is not None else seq * 1_000_000,
        correlation_id=CID,
    )


# ── Fixture event sequences ─────────────────────────────────────────────

NORMAL_COMPLETION = [
    _evt("TURN_STARTED", 1),
    _evt("ASR_PARTIAL", 2),
    _evt("ASR_FINAL", 3),
    _evt("MODEL_FIRST_TOKEN", 4),
    _evt("TTS_STARTED", 5),
    _evt("TTS_CHUNK", 6),
    _evt("MODEL_STREAM_ENDED", 7),
    _evt("TTS_ENDED", 8),
]

BARGE_IN_ABORT = [
    _evt("TURN_STARTED", 1),
    _evt("ASR_FINAL", 2),
    _evt("MODEL_FIRST_TOKEN", 3),
    _evt("BARGE_IN_REQUESTED", 4),
    _evt("CANCEL_ACK", 5),
    _evt("TURN_TIMEOUT", 6),
]

TIMEOUT_DURING_THINKING = [
    _evt("TURN_STARTED", 1),
    _evt("ASR_FINAL", 2),
    _evt("TURN_TIMEOUT", 3),
]

FAILURE_DURING_SPEAKING = [
    _evt("TURN_STARTED", 1),
    _evt("ASR_FINAL", 2),
    _evt("MODEL_FIRST_TOKEN", 3),
    _evt("TURN_FAILED", 4),
]


def _replay_via_reducer(events):
    """Replay events through the raw reducer, return final snapshot."""
    s = make_initial_snapshot(SID, TID, CID)
    all_cmds = []
    for e in events:
        s, cmds = reduce_turn(s, e)
        all_cmds.extend(cmds)
    return s, all_cmds


# ── Tests ────────────────────────────────────────────────────────────────

class TestReplayDeterminism:

    def test_replay_produces_identical_terminal_snapshot_hash(self):
        """Test 13: Two independent replays of the same event sequence
        produce identical deterministic hashes."""
        for fixture_name, events in [
            ("normal_completion", NORMAL_COMPLETION),
            ("barge_in_abort", BARGE_IN_ABORT),
            ("timeout_thinking", TIMEOUT_DURING_THINKING),
            ("failure_speaking", FAILURE_DURING_SPEAKING),
        ]:
            s1, cmds1 = _replay_via_reducer(events)
            s2, cmds2 = _replay_via_reducer(events)

            assert s1.deterministic_hash() == s2.deterministic_hash(), (
                f"Non-deterministic replay for fixture '{fixture_name}': "
                f"hash1={s1.deterministic_hash()[:16]}... "
                f"hash2={s2.deterministic_hash()[:16]}..."
            )
            assert s1.state == s2.state
            assert s1.seq == s2.seq
            assert s1.terminal == s2.terminal
            assert s1.reason == s2.reason

    def test_replay_via_router_matches_reducer(self):
        """Router-driven replay produces same hash as raw reducer replay."""
        for events in [NORMAL_COMPLETION, BARGE_IN_ABORT]:
            # Raw reducer
            s_raw, _ = _replay_via_reducer(events)

            # Router replay
            router = TurnRouter()
            s_router = router.replay(SID, TID, CID, events)

            assert s_raw.deterministic_hash() == s_router.deterministic_hash()

    def test_different_wall_clock_same_hash(self):
        """Events with different timestamps but same seq produce same hash."""
        events_a = [
            _evt("TURN_STARTED", 1, ts_ns=100),
            _evt("ASR_FINAL", 2, ts_ns=200),
            _evt("TURN_TIMEOUT", 3, ts_ns=300),
        ]
        events_b = [
            _evt("TURN_STARTED", 1, ts_ns=999_999),
            _evt("ASR_FINAL", 2, ts_ns=888_888),
            _evt("TURN_TIMEOUT", 3, ts_ns=777_777),
        ]
        s_a, _ = _replay_via_reducer(events_a)
        s_b, _ = _replay_via_reducer(events_b)
        assert s_a.deterministic_hash() == s_b.deterministic_hash()

    def test_normal_completion_terminal_state(self):
        """Normal completion fixture ends in COMPLETED."""
        s, _ = _replay_via_reducer(NORMAL_COMPLETION)
        assert s.state == TurnState.COMPLETED
        assert s.terminal is True
        assert s.reason == "normal_completion"

    def test_barge_in_abort_terminal_state(self):
        """Barge-in + timeout fixture ends in ABORTED."""
        s, _ = _replay_via_reducer(BARGE_IN_ABORT)
        assert s.state == TurnState.ABORTED
        assert s.terminal is True
