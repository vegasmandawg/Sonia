"""
v2.6 UI Protocol Tests -- ACK FSM Exhaustive Verification

Tests the control ACK model and connection FSM protocol contracts
that the Zustand store + ConnectionManager implement. Since the UI
is TypeScript, these tests verify the *protocol logic* in Python
to ensure backend <-> UI contract correctness.

Tests (15):
  ACK Happy Path (4):
    1. Toggle mic: optimistic -> ACK -> confirmed
    2. Toggle cam: optimistic -> ACK -> confirmed
    3. Toggle privacy: optimistic -> ACK -> confirmed
    4. Toggle hold: optimistic -> ACK -> confirmed

  NACK Rollback (3):
    5. Toggle mic -> NACK -> rolled back
    6. Double toggle same field replaces pending
    7. NACK on non-pending field is no-op

  Timeout Rollback (3):
    8. Expired pending control is rolled back
    9. Non-expired pending is preserved
    10. Multiple expired controls rolled back atomically

  Connection FSM (3):
    11. 5-state FSM transitions: disconnected -> connecting -> connected
    12. Reconnect increments attempt counter
    13. markConnected resets reconnect counter

  Interrupt / Replay Protocol (2):
    14. Interrupt: request sets pending, ACK clears + returns to idle
    15. Replay: request sets pending, ACK clears
"""

import sys
import time

import pytest

sys.path.insert(0, r"S:")
sys.path.insert(0, r"S:\services\shared")


# ---------------------------------------------------------------------------
# Simulated ACK FSM (mirrors store.ts logic in Python)
# ---------------------------------------------------------------------------

class AckFSM:
    """
    Python mirror of the Zustand store's ACK model.
    Tests verify the same state transitions the UI implements.
    """

    TIMEOUT_MS = 5000

    def __init__(self):
        # Connection
        self.connection_status = "disconnected"
        self.reconnect_attempts = 0
        self.last_connected_at = None

        # Conversation
        self.conversation_state = "idle"

        # Controls
        self.mic_enabled = True
        self.cam_enabled = False
        self.privacy_enabled = False
        self.hold_active = False
        self.pending_controls = []  # list of dicts

        # Interrupt / replay
        self.interrupt_pending = False
        self.replay_pending = False

    # -- Connection FSM --

    def set_connection_status(self, status):
        assert status in ("disconnected", "connecting", "connected", "reconnecting", "error")
        self.connection_status = status

    def increment_reconnect(self):
        self.reconnect_attempts += 1

    def reset_reconnect(self):
        self.reconnect_attempts = 0

    def mark_connected(self):
        self.connection_status = "connected"
        self.reconnect_attempts = 0
        self.last_connected_at = time.time()

    # -- Control toggles (optimistic + ACK) --

    def _toggle_field(self, field_name):
        current = getattr(self, field_name)
        target = not current
        pending = {
            "field": field_name,
            "target_value": target,
            "sent_at": time.time(),
            "timeout_ms": self.TIMEOUT_MS,
        }
        # Replace existing pending for same field
        self.pending_controls = [
            p for p in self.pending_controls if p["field"] != field_name
        ]
        self.pending_controls.append(pending)
        setattr(self, field_name, target)
        return pending

    def request_toggle_mic(self):
        return self._toggle_field("mic_enabled")

    def request_toggle_cam(self):
        return self._toggle_field("cam_enabled")

    def request_toggle_privacy(self):
        return self._toggle_field("privacy_enabled")

    def request_toggle_hold(self):
        return self._toggle_field("hold_active")

    def ack_control(self, field):
        self.pending_controls = [
            p for p in self.pending_controls if p["field"] != field
        ]

    def nack_control(self, field):
        pending = next((p for p in self.pending_controls if p["field"] == field), None)
        if pending:
            setattr(self, field, not pending["target_value"])
            self.pending_controls = [
                p for p in self.pending_controls if p["field"] != field
            ]

    def expire_pending_controls(self, now=None):
        if now is None:
            now = time.time()
        now_ms = now * 1000
        expired = [
            p for p in self.pending_controls
            if (now_ms - p["sent_at"] * 1000) > p["timeout_ms"]
        ]
        if not expired:
            return
        for p in expired:
            setattr(self, p["field"], not p["target_value"])
        self.pending_controls = [
            p for p in self.pending_controls
            if (now_ms - p["sent_at"] * 1000) <= p["timeout_ms"]
        ]

    # -- Interrupt / replay --

    def request_interrupt(self):
        self.interrupt_pending = True

    def ack_interrupt(self):
        self.interrupt_pending = False
        self.conversation_state = "idle"

    def request_replay(self):
        self.replay_pending = True

    def ack_replay(self):
        self.replay_pending = False


# ===========================================================================
# ACK Happy Path
# ===========================================================================

class TestAckHappyPath:

    def test_toggle_mic_ack(self):
        fsm = AckFSM()
        assert fsm.mic_enabled is True
        pending = fsm.request_toggle_mic()
        assert fsm.mic_enabled is False  # optimistic
        assert len(fsm.pending_controls) == 1
        assert pending["field"] == "mic_enabled"
        fsm.ack_control("mic_enabled")
        assert fsm.mic_enabled is False  # confirmed
        assert len(fsm.pending_controls) == 0

    def test_toggle_cam_ack(self):
        fsm = AckFSM()
        assert fsm.cam_enabled is False
        pending = fsm.request_toggle_cam()
        assert fsm.cam_enabled is True  # optimistic
        fsm.ack_control("cam_enabled")
        assert fsm.cam_enabled is True  # confirmed
        assert len(fsm.pending_controls) == 0

    def test_toggle_privacy_ack(self):
        fsm = AckFSM()
        assert fsm.privacy_enabled is False
        pending = fsm.request_toggle_privacy()
        assert fsm.privacy_enabled is True  # optimistic
        fsm.ack_control("privacy_enabled")
        assert fsm.privacy_enabled is True  # confirmed
        assert len(fsm.pending_controls) == 0

    def test_toggle_hold_ack(self):
        fsm = AckFSM()
        assert fsm.hold_active is False
        pending = fsm.request_toggle_hold()
        assert fsm.hold_active is True  # optimistic
        fsm.ack_control("hold_active")
        assert fsm.hold_active is True  # confirmed
        assert len(fsm.pending_controls) == 0


# ===========================================================================
# NACK Rollback
# ===========================================================================

class TestNackRollback:

    def test_toggle_mic_nack_rollback(self):
        fsm = AckFSM()
        assert fsm.mic_enabled is True
        fsm.request_toggle_mic()
        assert fsm.mic_enabled is False  # optimistic
        fsm.nack_control("mic_enabled")
        assert fsm.mic_enabled is True  # rolled back
        assert len(fsm.pending_controls) == 0

    def test_double_toggle_replaces_pending(self):
        fsm = AckFSM()
        assert fsm.mic_enabled is True
        fsm.request_toggle_mic()
        assert fsm.mic_enabled is False
        # Toggle again before ACK
        fsm.request_toggle_mic()
        assert fsm.mic_enabled is True  # back to original
        # Only one pending for this field
        mic_pendings = [p for p in fsm.pending_controls if p["field"] == "mic_enabled"]
        assert len(mic_pendings) == 1
        assert mic_pendings[0]["target_value"] is True

    def test_nack_nonpending_field_noop(self):
        fsm = AckFSM()
        assert fsm.mic_enabled is True
        # NACK on a field with no pending should be no-op
        fsm.nack_control("mic_enabled")
        assert fsm.mic_enabled is True
        assert len(fsm.pending_controls) == 0


# ===========================================================================
# Timeout Rollback
# ===========================================================================

class TestTimeoutRollback:

    def test_expired_pending_rolled_back(self):
        fsm = AckFSM()
        fsm.request_toggle_mic()
        assert fsm.mic_enabled is False
        # Manually backdate the pending
        fsm.pending_controls[0]["sent_at"] = time.time() - 10  # 10s ago
        fsm.expire_pending_controls()
        assert fsm.mic_enabled is True  # rolled back
        assert len(fsm.pending_controls) == 0

    def test_non_expired_preserved(self):
        fsm = AckFSM()
        fsm.request_toggle_mic()
        assert fsm.mic_enabled is False
        # Just created, should not expire
        fsm.expire_pending_controls()
        assert fsm.mic_enabled is False  # still optimistic
        assert len(fsm.pending_controls) == 1

    def test_multiple_expired_rolled_back(self):
        fsm = AckFSM()
        fsm.request_toggle_mic()   # True -> False
        fsm.request_toggle_cam()   # False -> True
        fsm.request_toggle_hold()  # False -> True
        assert fsm.mic_enabled is False
        assert fsm.cam_enabled is True
        assert fsm.hold_active is True
        assert len(fsm.pending_controls) == 3
        # Backdate all
        old_time = time.time() - 10
        for p in fsm.pending_controls:
            p["sent_at"] = old_time
        fsm.expire_pending_controls()
        # All rolled back
        assert fsm.mic_enabled is True
        assert fsm.cam_enabled is False
        assert fsm.hold_active is False
        assert len(fsm.pending_controls) == 0


# ===========================================================================
# Connection FSM
# ===========================================================================

class TestConnectionFSM:

    def test_5_state_transitions(self):
        fsm = AckFSM()
        assert fsm.connection_status == "disconnected"
        fsm.set_connection_status("connecting")
        assert fsm.connection_status == "connecting"
        fsm.mark_connected()
        assert fsm.connection_status == "connected"
        assert fsm.last_connected_at is not None
        fsm.set_connection_status("reconnecting")
        assert fsm.connection_status == "reconnecting"
        fsm.set_connection_status("error")
        assert fsm.connection_status == "error"

    def test_reconnect_increments(self):
        fsm = AckFSM()
        assert fsm.reconnect_attempts == 0
        fsm.increment_reconnect()
        assert fsm.reconnect_attempts == 1
        fsm.increment_reconnect()
        assert fsm.reconnect_attempts == 2
        fsm.increment_reconnect()
        assert fsm.reconnect_attempts == 3

    def test_mark_connected_resets_counter(self):
        fsm = AckFSM()
        fsm.increment_reconnect()
        fsm.increment_reconnect()
        assert fsm.reconnect_attempts == 2
        fsm.set_connection_status("reconnecting")
        fsm.mark_connected()
        assert fsm.reconnect_attempts == 0
        assert fsm.connection_status == "connected"


# ===========================================================================
# Interrupt / Replay Protocol
# ===========================================================================

class TestInterruptReplayProtocol:

    def test_interrupt_request_and_ack(self):
        fsm = AckFSM()
        fsm.conversation_state = "speaking"
        assert fsm.interrupt_pending is False
        fsm.request_interrupt()
        assert fsm.interrupt_pending is True
        assert fsm.conversation_state == "speaking"  # still speaking until ACK
        fsm.ack_interrupt()
        assert fsm.interrupt_pending is False
        assert fsm.conversation_state == "idle"  # reset to idle on ACK

    def test_replay_request_and_ack(self):
        fsm = AckFSM()
        assert fsm.replay_pending is False
        fsm.request_replay()
        assert fsm.replay_pending is True
        fsm.ack_replay()
        assert fsm.replay_pending is False
