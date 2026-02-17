"""
Consent State Machine (v4.3 Epic C)

Formal consent model for perception/vision. No inference path
may bypass consent state. Fail-closed: unknown state = denied.

States: OFF -> REQUESTED -> GRANTED -> ACTIVE -> REVOKED
Transitions are auditable with timestamps and correlation IDs.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Consent states
# ---------------------------------------------------------------------------

class ConsentState(str, Enum):
    OFF = "OFF"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Valid transitions (source -> set of allowed targets)
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: Dict[ConsentState, set] = {
    ConsentState.OFF: {ConsentState.REQUESTED},
    ConsentState.REQUESTED: {ConsentState.GRANTED, ConsentState.REVOKED},
    ConsentState.GRANTED: {ConsentState.ACTIVE, ConsentState.REVOKED},
    ConsentState.ACTIVE: {ConsentState.REVOKED},
    ConsentState.REVOKED: set(),  # terminal state
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConsentViolation(Exception):
    """Raised when an invalid consent state transition is attempted."""

    def __init__(self, session_id: str, from_state: ConsentState, to_state: ConsentState):
        self.session_id = session_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid consent transition for session {session_id}: "
            f"{from_state.value} -> {to_state.value}"
        )


# ---------------------------------------------------------------------------
# Consent record
# ---------------------------------------------------------------------------

class ConsentRecord:
    """Immutable-ish record of consent state for a single session."""

    __slots__ = (
        "state",
        "session_id",
        "granted_at",
        "revoked_at",
        "last_transition_at",
        "correlation_id",
        "audit_trail",
    )

    def __init__(self, session_id: str, correlation_id: str = ""):
        self.state: ConsentState = ConsentState.OFF
        self.session_id: str = session_id
        self.granted_at: Optional[float] = None
        self.revoked_at: Optional[float] = None
        self.last_transition_at: float = time.time()
        self.correlation_id: str = correlation_id
        self.audit_trail: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "session_id": self.session_id,
            "granted_at": self.granted_at,
            "revoked_at": self.revoked_at,
            "last_transition_at": self.last_transition_at,
            "correlation_id": self.correlation_id,
            "audit_trail": list(self.audit_trail),
        }


# ---------------------------------------------------------------------------
# Consent manager
# ---------------------------------------------------------------------------

class ConsentManager:
    """
    Thread-safe, per-session consent state machine.

    Every transition is validated against _VALID_TRANSITIONS and appended
    to an audit trail with timestamp and correlation ID.

    Fail-closed: is_inference_allowed returns False for unknown sessions
    or any state other than ACTIVE.
    """

    def __init__(self) -> None:
        self._records: Dict[str, ConsentRecord] = {}
        self._lock = threading.Lock()

    # -- internal helpers ---------------------------------------------------

    def _get_or_create(self, session_id: str, correlation_id: str) -> ConsentRecord:
        """Return existing record or create a new OFF record."""
        if session_id not in self._records:
            self._records[session_id] = ConsentRecord(
                session_id=session_id,
                correlation_id=correlation_id,
            )
        return self._records[session_id]

    def _transition(
        self,
        session_id: str,
        target: ConsentState,
        correlation_id: str,
    ) -> ConsentRecord:
        """Execute a state transition with validation and audit."""
        with self._lock:
            record = self._get_or_create(session_id, correlation_id)
            from_state = record.state

            # Validate transition
            allowed = _VALID_TRANSITIONS.get(from_state, set())
            if target not in allowed:
                raise ConsentViolation(session_id, from_state, target)

            # Apply transition
            now = time.time()
            record.audit_trail.append({
                "from_state": from_state.value,
                "to_state": target.value,
                "timestamp": now,
                "correlation_id": correlation_id,
            })
            record.state = target
            record.last_transition_at = now
            record.correlation_id = correlation_id

            if target == ConsentState.GRANTED:
                record.granted_at = now
            elif target == ConsentState.REVOKED:
                record.revoked_at = now

            return record

    # -- public API ---------------------------------------------------------

    def request_consent(self, session_id: str, correlation_id: str = "") -> ConsentRecord:
        """OFF -> REQUESTED. Initiates consent flow for a session."""
        return self._transition(session_id, ConsentState.REQUESTED, correlation_id)

    def grant_consent(self, session_id: str, correlation_id: str = "") -> ConsentRecord:
        """REQUESTED -> GRANTED. User has granted consent."""
        return self._transition(session_id, ConsentState.GRANTED, correlation_id)

    def activate_consent(self, session_id: str, correlation_id: str = "") -> ConsentRecord:
        """GRANTED -> ACTIVE. Consent is now active for inference."""
        return self._transition(session_id, ConsentState.ACTIVE, correlation_id)

    def revoke_consent(self, session_id: str, correlation_id: str = "") -> ConsentRecord:
        """any -> REVOKED. User has revoked consent. Terminal state."""
        with self._lock:
            record = self._get_or_create(session_id, correlation_id)
            from_state = record.state

            # Revocation is special: allowed from any non-REVOKED state
            if from_state == ConsentState.REVOKED:
                raise ConsentViolation(session_id, from_state, ConsentState.REVOKED)

            now = time.time()
            record.audit_trail.append({
                "from_state": from_state.value,
                "to_state": ConsentState.REVOKED.value,
                "timestamp": now,
                "correlation_id": correlation_id,
            })
            record.state = ConsentState.REVOKED
            record.last_transition_at = now
            record.revoked_at = now
            record.correlation_id = correlation_id
            return record

    def get_consent(self, session_id: str) -> Optional[ConsentRecord]:
        """Return the current consent record for a session, or None."""
        with self._lock:
            return self._records.get(session_id)

    def is_inference_allowed(self, session_id: str) -> bool:
        """
        Fail-closed check: returns True ONLY if consent state is ACTIVE.
        Unknown sessions, errors, or any other state returns False.
        """
        try:
            with self._lock:
                record = self._records.get(session_id)
                if record is None:
                    return False
                return record.state == ConsentState.ACTIVE
        except Exception:
            # Fail-closed on any error
            return False
