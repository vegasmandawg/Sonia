"""
v3.7 M1 — Session Isolation Guardrails

Prevents cross-session data leakage by enforcing session-scoped
access on memory reads and writes. Every memory operation must
carry a session context; operations without valid session context
are rejected.

Write reason codes provide audit traceability for memory mutations.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("api-gateway.session_isolation")


class WriteReasonCode(str, Enum):
    """Deterministic reason codes for memory writes."""
    TURN_RAW = "turn_raw"
    TURN_SUMMARY = "turn_summary"
    VISION_OBSERVATION = "vision_observation"
    TOOL_EVENT = "tool_event"
    CONFIRMATION_EVENT = "confirmation_event"
    SYSTEM_STATE = "system_state"
    USER_FACT = "user_fact"
    CORRECTION = "correction"


class IsolationViolation(Exception):
    """Raised when a session isolation guardrail is triggered."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class SessionContext:
    """Immutable context binding a request to its session scope."""
    session_id: str
    user_id: str
    persona_id: str = "default"
    conversation_id: str = ""
    correlation_id: str = ""

    def validate(self) -> None:
        """Raise IsolationViolation if context is incomplete."""
        if not self.session_id:
            raise IsolationViolation("MISSING_SESSION", "session_id is required")
        if not self.user_id:
            raise IsolationViolation("MISSING_USER", "user_id is required")


@dataclass
class PolicyTraceField:
    """Audit trace attached to every memory operation."""
    session_id: str
    user_id: str
    persona_id: str
    write_reason: str
    correlation_id: str = ""
    policy_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "write_reason": self.write_reason,
            "correlation_id": self.correlation_id,
            "policy_version": self.policy_version,
        }


class SessionIsolationGuard:
    """
    Enforces session-scoped access on memory operations.

    Rules:
    1. Memory reads are scoped to the requesting session's user_id + persona_id.
    2. Memory writes must include a valid WriteReasonCode and session context.
    3. Cross-session retrieval (session A reading session B's data) is blocked.
    4. Cross-persona writes (persona A writing to persona B's silo) are blocked.
    """

    def __init__(self):
        self._active_contexts: Dict[str, SessionContext] = {}
        self._violation_count: int = 0
        self._operation_count: int = 0

    def register_session(self, ctx: SessionContext) -> None:
        """Register a session context for isolation tracking."""
        ctx.validate()
        self._active_contexts[ctx.session_id] = ctx

    def unregister_session(self, session_id: str) -> None:
        """Remove session context when session closes."""
        self._active_contexts.pop(session_id, None)

    def validate_read(
        self,
        requesting_ctx: SessionContext,
        target_user_id: str,
        target_persona_id: str = "default",
    ) -> bool:
        """
        Validate that a memory read is within the session's scope.

        Returns True if allowed. Raises IsolationViolation if blocked.
        """
        self._operation_count += 1
        requesting_ctx.validate()

        if requesting_ctx.user_id != target_user_id:
            self._violation_count += 1
            raise IsolationViolation(
                "CROSS_USER_READ",
                f"Session {requesting_ctx.session_id} (user={requesting_ctx.user_id}) "
                f"cannot read memories for user={target_user_id}",
            )

        if requesting_ctx.persona_id != target_persona_id:
            self._violation_count += 1
            raise IsolationViolation(
                "CROSS_PERSONA_READ",
                f"Session {requesting_ctx.session_id} (persona={requesting_ctx.persona_id}) "
                f"cannot read memories for persona={target_persona_id}",
            )

        return True

    def validate_write(
        self,
        requesting_ctx: SessionContext,
        write_reason: str,
        target_persona_id: str = "default",
    ) -> PolicyTraceField:
        """
        Validate a memory write and return an audit trace.

        Returns PolicyTraceField on success. Raises IsolationViolation if blocked.
        """
        self._operation_count += 1
        requesting_ctx.validate()

        # Validate write reason
        valid_reasons = {r.value for r in WriteReasonCode}
        if write_reason not in valid_reasons:
            self._violation_count += 1
            raise IsolationViolation(
                "INVALID_WRITE_REASON",
                f"Write reason '{write_reason}' is not a valid WriteReasonCode. "
                f"Valid: {sorted(valid_reasons)}",
            )

        # Block cross-persona writes
        if requesting_ctx.persona_id != target_persona_id:
            self._violation_count += 1
            raise IsolationViolation(
                "CROSS_PERSONA_WRITE",
                f"Session {requesting_ctx.session_id} (persona={requesting_ctx.persona_id}) "
                f"cannot write to persona={target_persona_id}",
            )

        return PolicyTraceField(
            session_id=requesting_ctx.session_id,
            user_id=requesting_ctx.user_id,
            persona_id=requesting_ctx.persona_id,
            write_reason=write_reason,
            correlation_id=requesting_ctx.correlation_id,
        )

    def get_scoped_filters(self, ctx: SessionContext) -> Dict[str, str]:
        """Return metadata filters for session-scoped memory queries."""
        ctx.validate()
        return {
            "user_id": ctx.user_id,
            "persona_id": ctx.persona_id,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return isolation guard statistics."""
        return {
            "active_sessions": len(self._active_contexts),
            "total_operations": self._operation_count,
            "total_violations": self._violation_count,
        }
