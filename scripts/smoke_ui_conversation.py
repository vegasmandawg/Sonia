"""
Smoke test: UI conversation loop (Phase 2)

Connects to WS /v1/ui/stream and tests:
1. session.created on connect
2. input.text -> turn.user echo
3. input.text -> state.conversation transitions (idle->thinking->...)
4. input.text -> turn.assistant OR error (depends on backend availability)
5. Empty input.text rejection
6. Turn-in-progress guard
7. Diagnostics push
"""

import asyncio
import json
import sys
import os
import time

# Force UTF-8 output on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Use the websockets library
try:
    import websockets
except ImportError:
    print("FAIL: websockets not installed")
    sys.exit(1)

WS_URL = "ws://127.0.0.1:7000/v1/ui/stream"
TIMEOUT = 10  # seconds per test

results = []

def record(name: str, passed: bool, detail: str = ""):
    tag = "PASS" if passed else "FAIL"
    results.append((name, passed))
    msg = f"  [{tag}] {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)


async def recv_until(ws, msg_type: str, timeout: float = TIMEOUT):
    """Receive messages until we get one with the given type, or timeout."""
    deadline = time.time() + timeout
    collected = []
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            collected.append(msg)
            if msg.get("type") == msg_type:
                return msg, collected
        except asyncio.TimeoutError:
            break
        except Exception as e:
            break
    return None, collected


async def recv_all(ws, timeout: float = 2.0):
    """Drain all pending messages within timeout."""
    msgs = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msgs.append(json.loads(raw))
        except asyncio.TimeoutError:
            break
        except Exception:
            break
    return msgs


async def test_session_created():
    """T1: Connect and receive session.created."""
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            msg, _ = await recv_until(ws, "session.created", timeout=5)
            if msg and msg.get("session_id"):
                record("T1: session.created", True, f"session_id={msg['session_id']}")
            else:
                record("T1: session.created", False, "no session.created received")
    except Exception as e:
        record("T1: session.created", False, str(e))


async def test_empty_input_rejected():
    """T2: Empty input.text should be rejected."""
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # Consume session.created
            await recv_until(ws, "session.created", timeout=5)

            # Send empty text
            await ws.send(json.dumps({"type": "input.text", "text": ""}))
            msg, _ = await recv_until(ws, "error", timeout=5)
            if msg and "empty_input_text" in msg.get("message", ""):
                record("T2: empty input rejected", True)
            else:
                record("T2: empty input rejected", False, f"got: {msg}")
    except Exception as e:
        record("T2: empty input rejected", False, str(e))


async def test_text_turn_flow():
    """T3-T5: Send input.text and verify turn.user echo + state transitions + response/error."""
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # Consume session.created
            await recv_until(ws, "session.created", timeout=5)

            # Send a text message
            test_text = "Hello Sonia, this is a smoke test."
            await ws.send(json.dumps({"type": "input.text", "text": test_text}))

            # Collect messages for up to 30 seconds (turn pipeline has 10s timeout per service)
            msgs = []
            deadline = time.time() + 30
            got_idle_back = False
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    msgs.append(msg)
                    # Stop once we see conversation state return to idle
                    if msg.get("type") == "state.conversation" and msg.get("state") == "idle":
                        got_idle_back = True
                        break
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break

            types = [m.get("type") for m in msgs]

            # T3: turn.user echo
            user_msgs = [m for m in msgs if m.get("type") == "turn.user"]
            if user_msgs and user_msgs[0].get("text") == test_text:
                record("T3: turn.user echo", True)
            else:
                record("T3: turn.user echo", False, f"types seen: {types}")

            # T4: state.conversation thinking
            thinking_msgs = [m for m in msgs if m.get("type") == "state.conversation" and m.get("state") == "thinking"]
            if thinking_msgs:
                record("T4: state->thinking", True)
            else:
                record("T4: state->thinking", False, f"types seen: {types}")

            # T5: turn.assistant or error (both are valid since model-router may not be running)
            assistant_msgs = [m for m in msgs if m.get("type") == "turn.assistant"]
            error_msgs = [m for m in msgs if m.get("type") == "error"]
            if assistant_msgs:
                text = assistant_msgs[0].get("text", "")[:80]
                record("T5: turn response", True, f"assistant: {text}...")
            elif error_msgs:
                err = error_msgs[0].get("message", "")
                record("T5: turn response", True, f"error (expected, services down): {err}")
            else:
                record("T5: turn response", False, f"no assistant or error. types: {types}")

            # T5b: state returns to idle
            if got_idle_back:
                record("T5b: state->idle (cleanup)", True)
            else:
                idle_msgs = [m for m in msgs if m.get("type") == "state.conversation" and m.get("state") == "idle"]
                record("T5b: state->idle (cleanup)", bool(idle_msgs), f"types: {types}")

    except Exception as e:
        record("T3: turn.user echo", False, str(e))
        record("T4: state->thinking", False, "skipped")
        record("T5: turn response", False, "skipped")
        record("T5b: state->idle (cleanup)", False, "skipped")


async def test_turn_in_progress_guard():
    """T6: Sending input.text while a turn is in progress should be rejected."""
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # Consume session.created
            await recv_until(ws, "session.created", timeout=5)

            # Send first text (will start processing)
            await ws.send(json.dumps({"type": "input.text", "text": "First message"}))

            # Wait for thinking state
            msg, _ = await recv_until(ws, "state.conversation", timeout=5)

            # Immediately send second text
            await ws.send(json.dumps({"type": "input.text", "text": "Second message while busy"}))

            # Look for turn_in_progress error
            deadline = time.time() + 5
            found_guard = False
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    if msg.get("type") == "error" and "turn_in_progress" in msg.get("message", ""):
                        found_guard = True
                        break
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break

            record("T6: turn_in_progress guard", found_guard)
    except Exception as e:
        record("T6: turn_in_progress guard", False, str(e))


async def test_diagnostics_push():
    """T7: Diagnostics should be pushed periodically."""
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # Consume session.created
            await recv_until(ws, "session.created", timeout=5)

            # Wait for diagnostics (default interval is 5s)
            msg, _ = await recv_until(ws, "diagnostics", timeout=8)
            if msg and msg.get("data"):
                data = msg["data"]
                has_keys = all(k in data for k in ["session_id", "uptime_seconds", "turn_count"])
                record("T7: diagnostics push", has_keys, f"keys: {list(data.keys())}")
            else:
                record("T7: diagnostics push", False, "no diagnostics received within 8s")
    except Exception as e:
        record("T7: diagnostics push", False, str(e))


async def main():
    print("=" * 60)
    print("SONIA Phase 2 -- UI Conversation Loop Smoke Test")
    print("=" * 60)
    print(f"Target: {WS_URL}")
    print()

    await test_session_created()
    await test_empty_input_rejected()
    await test_text_turn_flow()
    await test_turn_in_progress_guard()
    await test_diagnostics_push()

    print()
    print("-" * 60)
    passed = sum(1 for _, p in results if p)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    if passed == total:
        print("ALL TESTS PASSED")
    else:
        failed = [n for n, p in results if not p]
        print(f"FAILED: {', '.join(failed)}")
    print("-" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
