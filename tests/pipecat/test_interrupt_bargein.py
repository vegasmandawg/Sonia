"""
Tests for app.interruptions — Interrupt / Barge-In Handling

Verifies:
    I1. Interrupt from IDLE is rejected.
    I2. Interrupt from LISTENING is rejected.
    I3. Interrupt from THINKING succeeds, returns to IDLE.
    I4. Interrupt from SPEAKING succeeds, returns to IDLE.
    I5. Cancel events are set on interrupt.
    I6. Cancel events are cleared after full recovery.
    I7. Debounce rejects rapid re-interrupt.
    I8. Debounce allows interrupt after window expires.
    I9. recover_to_idle=False leaves state at INTERRUPTED.
    I10. InterruptResult fields are populated correctly.
    I11. clear_interrupt_state cleans up session tracking.
    I12. Concurrent interrupts on same session are serialised.
"""

import asyncio
import sys
import os
import time

for _m in list(sys.modules):
    if _m == "app" or _m.startswith("app."):
        sys.modules.pop(_m, None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipecat"))

from app.turn_taking import TurnState, transition, remove_lock
from app.session_manager import VoiceSession
from app.interruptions import (
    handle_interrupt, InterruptResult,
    clear_interrupt_state, DEFAULT_DEBOUNCE_SECS,
)


async def _setup_session(sid, target_state):
    """Helper: create a session and drive it to target_state."""
    s = VoiceSession(session_id=sid)
    path = {
        TurnState.IDLE: [],
        TurnState.LISTENING: [TurnState.LISTENING],
        TurnState.THINKING: [TurnState.LISTENING, TurnState.THINKING],
        TurnState.SPEAKING: [TurnState.LISTENING, TurnState.THINKING, TurnState.SPEAKING],
    }
    for t in path.get(target_state, []):
        await transition(s, t, reason="setup")
    return s


async def _test_i1():
    s = await _setup_session("i1", TurnState.IDLE)
    res = await handle_interrupt(s, reason="test")
    assert not res.accepted
    assert s.turn_state == TurnState.IDLE
    remove_lock(s.session_id)


async def _test_i2():
    s = await _setup_session("i2", TurnState.LISTENING)
    res = await handle_interrupt(s, reason="test")
    assert not res.accepted
    assert s.turn_state == TurnState.LISTENING
    remove_lock(s.session_id)


async def _test_i3():
    s = await _setup_session("i3", TurnState.THINKING)
    res = await handle_interrupt(s, reason="barge_in")
    assert res.accepted
    assert res.previous_state == "THINKING"
    assert s.turn_state == TurnState.IDLE
    remove_lock(s.session_id)


async def _test_i4():
    s = await _setup_session("i4", TurnState.SPEAKING)
    res = await handle_interrupt(s, reason="barge_in")
    assert res.accepted
    assert res.previous_state == "SPEAKING"
    assert s.turn_state == TurnState.IDLE
    remove_lock(s.session_id)


async def _test_i5():
    s = await _setup_session("i5", TurnState.SPEAKING)
    res = await handle_interrupt(s, reason="test", recover_to_idle=False)
    assert res.accepted
    assert s.cancel_infer_evt.is_set()
    assert s.cancel_tts_evt.is_set()
    remove_lock(s.session_id)


async def _test_i6():
    s = await _setup_session("i6", TurnState.THINKING)
    await handle_interrupt(s, reason="test", recover_to_idle=True)
    assert not s.cancel_infer_evt.is_set(), "should be cleared after recovery"
    assert not s.cancel_tts_evt.is_set(), "should be cleared after recovery"
    assert s.turn_state == TurnState.IDLE
    remove_lock(s.session_id)


async def _test_i7():
    s = await _setup_session("i7", TurnState.SPEAKING)
    res1 = await handle_interrupt(s, reason="first")
    assert res1.accepted

    # Immediately try again (within debounce)
    s2 = await _setup_session("i7", TurnState.SPEAKING)
    res2 = await handle_interrupt(s2, reason="second", debounce_secs=10.0)
    assert not res2.accepted
    assert res2.debounced
    clear_interrupt_state("i7")
    remove_lock("i7")


async def _test_i8():
    clear_interrupt_state("i8")
    s = await _setup_session("i8", TurnState.SPEAKING)
    res1 = await handle_interrupt(s, reason="first", debounce_secs=0.01)
    assert res1.accepted

    await asyncio.sleep(0.02)  # exceed debounce window

    s2 = await _setup_session("i8", TurnState.THINKING)
    res2 = await handle_interrupt(s2, reason="second", debounce_secs=0.01)
    assert res2.accepted, "Should be accepted after debounce window"
    clear_interrupt_state("i8")
    remove_lock("i8")


async def _test_i9():
    s = await _setup_session("i9", TurnState.SPEAKING)
    res = await handle_interrupt(s, reason="test", recover_to_idle=False)
    assert res.accepted
    assert s.turn_state == TurnState.INTERRUPTED
    remove_lock(s.session_id)


async def _test_i10():
    s = await _setup_session("i10", TurnState.SPEAKING)
    res = await handle_interrupt(s, reason="user_spoke", trace_id="tr10")
    assert isinstance(res, InterruptResult)
    assert res.accepted is True
    assert res.reason == "user_spoke"
    assert res.previous_state == "SPEAKING"
    assert res.new_state == "IDLE"
    assert res.state_seq > 0
    assert res.debounced is False
    clear_interrupt_state(s.session_id)
    remove_lock(s.session_id)


async def _test_i11():
    # Just verify it doesn't raise
    clear_interrupt_state("nonexistent")
    clear_interrupt_state("i11")


async def _test_i12():
    """Concurrent interrupts should be serialised by the per-session lock."""
    s = await _setup_session("i12", TurnState.SPEAKING)
    clear_interrupt_state("i12")

    results = []

    async def try_interrupt(delay):
        await asyncio.sleep(delay)
        res = await handle_interrupt(s, reason="concurrent", debounce_secs=0.0)
        results.append(res)

    await asyncio.gather(
        try_interrupt(0.0),
        try_interrupt(0.001),
    )

    # At most one should be accepted (the first one transitions to IDLE,
    # the second finds state = IDLE which is not interruptible)
    accepted = [r for r in results if r.accepted]
    assert len(accepted) <= 1, f"Expected <=1 accepted, got {len(accepted)}"
    clear_interrupt_state("i12")
    remove_lock("i12")


def run_all():
    tests = [
        ("I1: IDLE rejected", _test_i1),
        ("I2: LISTENING rejected", _test_i2),
        ("I3: THINKING accepted", _test_i3),
        ("I4: SPEAKING accepted", _test_i4),
        ("I5: cancel events set", _test_i5),
        ("I6: cancel events cleared", _test_i6),
        ("I7: debounce rejects", _test_i7),
        ("I8: debounce allows after window", _test_i8),
        ("I9: recover_to_idle=False", _test_i9),
        ("I10: InterruptResult fields", _test_i10),
        ("I11: clear_interrupt_state", _test_i11),
        ("I12: concurrent serialised", _test_i12),
    ]

    results = []
    for name, fn in tests:
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
