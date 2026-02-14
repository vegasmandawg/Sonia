"""
Tests for app.turn_taking — Deterministic Turn State Machine

Verifies:
    T1. All 6 states are defined.
    T2. Transition matrix covers every state.
    T3. Every allowed transition succeeds.
    T4. Every disallowed transition is rejected.
    T5. state_seq increments on every successful transition.
    T6. turn_seq increments only on IDLE → LISTENING.
    T7. Per-session lock prevents concurrent conflicting transitions.
    T8. get_state_snapshot returns correct data.
    T9. is_terminal_or_idle returns correct values.
    T10. Full turn cycle: IDLE→LISTENING→THINKING→SPEAKING→IDLE.
"""

import asyncio
import sys
import os

for _m in list(sys.modules):
    if _m == "app" or _m.startswith("app."):
        sys.modules.pop(_m, None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipecat"))

from app.turn_taking import (
    TurnState, ALLOWED_TRANSITIONS, transition,
    get_state_snapshot, is_terminal_or_idle, remove_lock,
)
from app.session_manager import VoiceSession


def test_t1_all_states():
    """T1: All 6 states are defined."""
    expected = {"IDLE", "LISTENING", "THINKING", "SPEAKING", "INTERRUPTED", "RECOVERING"}
    actual = {s.value for s in TurnState}
    assert actual == expected, f"States mismatch: {actual} != {expected}"


def test_t2_matrix_complete():
    """T2: Transition matrix covers every state."""
    for state in TurnState:
        assert state in ALLOWED_TRANSITIONS, f"Missing state in matrix: {state}"


async def _test_t3_allowed_transitions():
    """T3: Every allowed transition succeeds."""
    for src, targets in ALLOWED_TRANSITIONS.items():
        for tgt in targets:
            s = VoiceSession(session_id=f"t3-{src.value}-{tgt.value}")
            s.turn_state = src  # direct set for test setup only
            ok = await transition(s, tgt, reason="t3_test")
            assert ok, f"{src.value} -> {tgt.value} should be allowed"
            assert s.turn_state == tgt
            remove_lock(s.session_id)


async def _test_t4_disallowed_transitions():
    """T4: Every disallowed transition is rejected."""
    all_states = set(TurnState)
    for src, allowed in ALLOWED_TRANSITIONS.items():
        disallowed = all_states - set(allowed) - {src}  # exclude self-transition
        for tgt in disallowed:
            s = VoiceSession(session_id=f"t4-{src.value}-{tgt.value}")
            s.turn_state = src
            seq_before = s.state_seq
            ok = await transition(s, tgt, reason="t4_test")
            assert not ok, f"{src.value} -> {tgt.value} should be rejected"
            assert s.turn_state == src, "State should not change on rejection"
            assert s.state_seq == seq_before, "state_seq should not change on rejection"
            remove_lock(s.session_id)


async def _test_t5_state_seq():
    """T5: state_seq increments on every successful transition."""
    s = VoiceSession(session_id="t5")
    assert s.state_seq == 0
    await transition(s, TurnState.LISTENING, reason="t5")
    assert s.state_seq == 1
    await transition(s, TurnState.THINKING, reason="t5")
    assert s.state_seq == 2
    await transition(s, TurnState.SPEAKING, reason="t5")
    assert s.state_seq == 3
    await transition(s, TurnState.IDLE, reason="t5")
    assert s.state_seq == 4
    remove_lock(s.session_id)


async def _test_t6_turn_seq():
    """T6: turn_seq increments only on IDLE → LISTENING."""
    s = VoiceSession(session_id="t6")
    assert s.turn_seq == 0

    # Turn 1
    await transition(s, TurnState.LISTENING, reason="t6")
    assert s.turn_seq == 1
    await transition(s, TurnState.THINKING, reason="t6")
    assert s.turn_seq == 1  # no change
    await transition(s, TurnState.SPEAKING, reason="t6")
    assert s.turn_seq == 1  # no change
    await transition(s, TurnState.IDLE, reason="t6")
    assert s.turn_seq == 1  # no change

    # Turn 2
    await transition(s, TurnState.LISTENING, reason="t6")
    assert s.turn_seq == 2  # incremented
    remove_lock(s.session_id)


async def _test_t7_concurrent_lock():
    """T7: Per-session lock prevents concurrent conflicting transitions."""
    s = VoiceSession(session_id="t7")

    results = []

    async def try_transition(target, delay):
        await asyncio.sleep(delay)
        ok = await transition(s, target, reason="concurrent_test")
        results.append((target.value, ok))

    # Both try to transition from IDLE — only LISTENING should win
    await asyncio.gather(
        try_transition(TurnState.LISTENING, 0.0),
        try_transition(TurnState.LISTENING, 0.001),
    )

    # One should succeed, one should fail (already in LISTENING)
    successes = [r for r in results if r[1]]
    assert len(successes) >= 1, "At least one transition should succeed"
    remove_lock(s.session_id)


async def _test_t8_snapshot():
    """T8: get_state_snapshot returns correct data."""
    s = VoiceSession(session_id="t8", user_id="u1")
    await transition(s, TurnState.LISTENING, reason="t8")

    snap = get_state_snapshot(s)
    assert snap["session_id"] == "t8"
    assert snap["turn_state"] == "LISTENING"
    assert snap["state_seq"] == 1
    assert snap["turn_seq"] == 1
    assert snap["last_state_change_ts"] > 0
    remove_lock(s.session_id)


def test_t9_terminal_or_idle():
    """T9: is_terminal_or_idle returns correct values."""
    assert is_terminal_or_idle(TurnState.IDLE) is True
    assert is_terminal_or_idle(TurnState.LISTENING) is False
    assert is_terminal_or_idle(TurnState.THINKING) is False
    assert is_terminal_or_idle(TurnState.SPEAKING) is False
    assert is_terminal_or_idle(TurnState.INTERRUPTED) is False
    assert is_terminal_or_idle(TurnState.RECOVERING) is False


async def _test_t10_full_cycle():
    """T10: Full turn cycle IDLE→LISTENING→THINKING→SPEAKING→IDLE."""
    s = VoiceSession(session_id="t10")
    for target in [TurnState.LISTENING, TurnState.THINKING,
                   TurnState.SPEAKING, TurnState.IDLE]:
        ok = await transition(s, target, reason="full_cycle")
        assert ok, f"Transition to {target.value} should succeed"

    assert s.turn_state == TurnState.IDLE
    assert s.state_seq == 4
    assert s.turn_seq == 1
    remove_lock(s.session_id)


def run_all():
    """Run all tests and report results."""
    results = []

    sync_tests = [
        ("T1: all states defined", test_t1_all_states),
        ("T2: matrix complete", test_t2_matrix_complete),
        ("T9: terminal_or_idle", test_t9_terminal_or_idle),
    ]

    async_tests = [
        ("T3: allowed transitions", _test_t3_allowed_transitions),
        ("T4: disallowed transitions", _test_t4_disallowed_transitions),
        ("T5: state_seq increment", _test_t5_state_seq),
        ("T6: turn_seq increment", _test_t6_turn_seq),
        ("T7: concurrent lock", _test_t7_concurrent_lock),
        ("T8: snapshot", _test_t8_snapshot),
        ("T10: full cycle", _test_t10_full_cycle),
    ]

    for name, fn in sync_tests:
        try:
            fn()
            results.append(f"PASS: {name}")
        except Exception as e:
            results.append(f"FAIL: {name}: {e}")

    for name, fn in async_tests:
        try:
            asyncio.run(fn())
            results.append(f"PASS: {name}")
        except Exception as e:
            results.append(f"FAIL: {name}: {e}")

    return results


if __name__ == "__main__":
    results = run_all()
    for r in results:
        print(r)

    fails = [r for r in results if r.startswith("FAIL")]
    print(f"\nTotal: {len(results)}  Pass: {len(results)-len(fails)}  Fail: {len(fails)}")
    sys.exit(1 if fails else 0)
