"""
Tests for app.watchdog + app.asr_client — Watchdog & Recovery

Verifies:
    W1. run_with_timeout: normal completion returns value.
    W2. run_with_timeout: timeout aborts and reports.
    W3. run_with_timeout: raise_on_timeout raises StageTimeout.
    W4. run_with_timeout: cancel event aborts early.
    W5. run_with_timeout: error in coroutine captured.
    W6. transcribe_guarded: normal ASR decode returns result.
    W7. transcribe_guarded: timeout path with slow ASR.
    W8. transcribe_guarded: cancel path with pre-set event.
    W9. VoiceSessionManager.reset_to_idle from various states.
    W10. VoiceSessionManager.close cancels active tasks.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipecat"))

from app.watchdog import run_with_timeout, StageTimeout, WatchdogResult
from app.asr_client import transcribe_guarded
from app.turn_taking import TurnState, transition, remove_lock
from app.session_manager import VoiceSession, VoiceSessionManager


class MockASR:
    """Fast mock ASR backend."""
    async def transcribe(self, audio, partial=False):
        await asyncio.sleep(0.02)
        return {"text": "hello world", "confidence": 0.95, "partial": partial}


class SlowASR:
    """Slow mock ASR backend (always times out)."""
    async def transcribe(self, audio, partial=False):
        await asyncio.sleep(60.0)
        return {"text": "", "confidence": 0, "partial": partial}


class ErrorASR:
    """Mock ASR that raises."""
    async def transcribe(self, audio, partial=False):
        raise RuntimeError("ASR backend unavailable")


async def _test_w1():
    async def fast():
        await asyncio.sleep(0.02)
        return 42
    res = await run_with_timeout(fast(), timeout_secs=5.0, stage_name="w1")
    assert not res.timed_out
    assert not res.cancelled
    assert res.value == 42
    assert res.elapsed_ms >= 0  # monotonic, may round to 0 on fast systems


async def _test_w2():
    async def slow():
        await asyncio.sleep(60.0)
    res = await run_with_timeout(slow(), timeout_secs=0.05, stage_name="w2")
    assert res.timed_out
    assert res.value is None
    assert res.elapsed_ms >= 40


async def _test_w3():
    async def slow():
        await asyncio.sleep(60.0)
    try:
        await run_with_timeout(slow(), timeout_secs=0.05,
                               stage_name="w3", raise_on_timeout=True)
        assert False, "Should have raised"
    except StageTimeout as e:
        assert e.stage == "w3"
        assert e.timeout_secs == 0.05


async def _test_w4():
    evt = asyncio.Event()
    async def fire():
        await asyncio.sleep(0.02)
        evt.set()
    asyncio.create_task(fire())

    async def slow():
        await asyncio.sleep(60.0)

    res = await run_with_timeout(slow(), timeout_secs=5.0,
                                 stage_name="w4", cancel_evt=evt)
    assert res.cancelled
    assert not res.timed_out


async def _test_w5():
    async def bad():
        raise ValueError("test error")
    res = await run_with_timeout(bad(), timeout_secs=5.0, stage_name="w5")
    assert res.error is not None
    assert "test error" in res.error


async def _test_w6():
    s = VoiceSession(session_id="w6")
    res = await transcribe_guarded(s, b"\x00" * 100, MockASR(), trace_id="w6")
    assert not res.timed_out
    assert not res.cancelled
    assert res.value["text"] == "hello world"
    assert res.value["confidence"] == 0.95


async def _test_w7():
    s = VoiceSession(session_id="w7")
    res = await transcribe_guarded(s, b"\x00" * 100, SlowASR(),
                                   trace_id="w7", timeout_secs=0.05)
    assert res.timed_out


async def _test_w8():
    s = VoiceSession(session_id="w8")
    s.cancel_infer_evt.set()
    res = await transcribe_guarded(s, b"\x00" * 100, MockASR(), trace_id="w8")
    assert res.cancelled


async def _test_w9():
    mgr = VoiceSessionManager()

    # From SPEAKING
    s1 = mgr.create(user_id="u1", session_id="w9a")
    await transition(s1, TurnState.LISTENING, reason="t")
    await transition(s1, TurnState.THINKING, reason="t")
    await transition(s1, TurnState.SPEAKING, reason="t")
    ok = await mgr.reset_to_idle(s1, reason="test")
    assert ok
    assert s1.turn_state == TurnState.IDLE

    # From THINKING
    s2 = mgr.create(user_id="u2", session_id="w9b")
    await transition(s2, TurnState.LISTENING, reason="t")
    await transition(s2, TurnState.THINKING, reason="t")
    ok = await mgr.reset_to_idle(s2, reason="test")
    assert ok
    assert s2.turn_state == TurnState.IDLE

    # From INTERRUPTED
    s3 = mgr.create(user_id="u3", session_id="w9c")
    await transition(s3, TurnState.LISTENING, reason="t")
    await transition(s3, TurnState.THINKING, reason="t")
    await transition(s3, TurnState.INTERRUPTED, reason="t")
    ok = await mgr.reset_to_idle(s3, reason="test")
    assert ok
    assert s3.turn_state == TurnState.IDLE

    # Already IDLE
    s4 = mgr.create(user_id="u4", session_id="w9d")
    ok = await mgr.reset_to_idle(s4, reason="test")
    assert ok
    assert s4.turn_state == TurnState.IDLE

    await mgr.close_all()


async def _test_w10():
    mgr = VoiceSessionManager(cleanup_timeout=1.0)
    s = mgr.create(user_id="u1", session_id="w10")

    # Register a long-running task
    async def long_task():
        await asyncio.sleep(60.0)

    task = asyncio.create_task(long_task())
    s.register_task("long", task)
    assert len(s.active_tasks) == 1

    # Close should cancel the task
    closed = await mgr.close(s.session_id, reason="test")
    assert closed
    assert task.cancelled() or task.done()
    assert mgr.active_count == 0


def run_all():
    tests = [
        ("W1: normal completion", _test_w1),
        ("W2: timeout", _test_w2),
        ("W3: raise_on_timeout", _test_w3),
        ("W4: cancel event", _test_w4),
        ("W5: error capture", _test_w5),
        ("W6: ASR normal", _test_w6),
        ("W7: ASR timeout", _test_w7),
        ("W8: ASR cancel", _test_w8),
        ("W9: reset_to_idle", _test_w9),
        ("W10: close cancels tasks", _test_w10),
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
