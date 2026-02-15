"""Privacy boundary gate for perception pipeline (v3.3 Epic C).

Enforces strict privacy boundaries across all perception event flows.
When privacy mode is ACTIVE, PII patterns are scrubbed from envelopes.
When privacy mode is SUSPENDED, zero-frame guarantee applies (no processing).

Privacy State Machine:
    CLEAR     -> ACTIVE     (privacy filter engaged)
    CLEAR     -> SUSPENDED  (perception paused)
    ACTIVE    -> CLEAR      (privacy filter disengaged)
    ACTIVE    -> SUSPENDED  (perception paused)
    SUSPENDED -> CLEAR      (resume, must go through CLEAR first)

Key invariants:
    - SUSPENDED -> ACTIVE is NEVER valid (must clear first)
    - Zero-frame: no envelopes processed while SUSPENDED
    - PII scrubbing is deterministic and non-destructive to structure
    - All state transitions are auditable
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .event_normalizer import PerceptionEnvelope


class PrivacyState(str, Enum):
    """Privacy boundary states."""
    CLEAR = "clear"
    ACTIVE = "active"
    SUSPENDED = "suspended"


# Valid state transitions
VALID_TRANSITIONS = {
    PrivacyState.CLEAR: {PrivacyState.ACTIVE, PrivacyState.SUSPENDED},
    PrivacyState.ACTIVE: {PrivacyState.CLEAR, PrivacyState.SUSPENDED},
    PrivacyState.SUSPENDED: {PrivacyState.CLEAR},  # Never skip to ACTIVE
}


# PII patterns for scrubbing
PII_PATTERNS = [
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN_REDACTED]'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL_REDACTED]'),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE_REDACTED]'),
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CC_REDACTED]'),
]


@dataclass
class PrivacyTransition:
    """Record of a privacy state transition."""
    from_state: str
    to_state: str
    timestamp: float
    reason: str


class PrivacyGate:
    """Enforces privacy boundaries on perception pipeline.

    Invariants:
        1. SUSPENDED state = zero-frame (no envelopes pass through)
        2. ACTIVE state = PII scrubbing applied to all envelopes
        3. CLEAR state = pass-through (no modifications)
        4. SUSPENDED -> ACTIVE is never allowed
        5. All transitions are logged for audit
    """

    def __init__(self):
        self._state = PrivacyState.CLEAR
        self._transitions: List[PrivacyTransition] = []
        self._stats = {
            "envelopes_processed": 0,
            "envelopes_scrubbed": 0,
            "envelopes_blocked": 0,
            "pii_detections": 0,
            "invalid_transitions": 0,
        }

    @property
    def state(self) -> PrivacyState:
        return self._state

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def transitions(self) -> List[PrivacyTransition]:
        return list(self._transitions)

    def transition(self, target: PrivacyState, reason: str = "") -> bool:
        """Attempt a state transition.

        Returns True if transition was valid and applied.
        Returns False if transition is invalid (state unchanged).
        """
        if target == self._state:
            return True  # No-op

        valid = VALID_TRANSITIONS.get(self._state, set())
        if target not in valid:
            self._stats["invalid_transitions"] += 1
            return False

        record = PrivacyTransition(
            from_state=self._state.value,
            to_state=target.value,
            timestamp=time.time(),
            reason=reason,
        )
        self._transitions.append(record)
        self._state = target
        return True

    def process_envelope(
        self, envelope: PerceptionEnvelope
    ) -> Optional[Dict[str, Any]]:
        """Process an envelope through the privacy gate.

        Returns:
            Dict representation of the (possibly scrubbed) envelope,
            or None if blocked (SUSPENDED state).
        """
        if self._state == PrivacyState.SUSPENDED:
            self._stats["envelopes_blocked"] += 1
            return None  # Zero-frame guarantee

        self._stats["envelopes_processed"] += 1
        result = {
            "event_id": envelope.event_id,
            "session_id": envelope.session_id,
            "source": envelope.source,
            "event_type": envelope.event_type,
            "object_id": envelope.object_id,
            "content_hash": envelope.content_hash,
            "confidence": envelope.confidence,
            "correlation_id": envelope.correlation_id,
        }

        if self._state == PrivacyState.ACTIVE:
            # Scrub PII from string fields
            result = self._scrub_pii(result)
            self._stats["envelopes_scrubbed"] += 1

        return result

    def _scrub_pii(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply PII scrubbing patterns to all string values."""
        scrubbed = {}
        for key, value in data.items():
            if isinstance(value, str):
                for pattern, replacement in PII_PATTERNS:
                    if pattern.search(value):
                        self._stats["pii_detections"] += 1
                    value = pattern.sub(replacement, value)
            scrubbed[key] = value
        return scrubbed

    def get_audit_report(self) -> Dict[str, Any]:
        """Generate audit report for gate checks."""
        return {
            "current_state": self._state.value,
            "stats": self.stats,
            "transition_count": len(self._transitions),
            "transitions": [
                {
                    "from": t.from_state,
                    "to": t.to_state,
                    "reason": t.reason,
                }
                for t in self._transitions
            ],
        }
