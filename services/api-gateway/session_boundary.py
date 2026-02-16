"""Session Boundary Policy — v4.2 E1.

Enforces session namespace isolation: each session has a unique ID and
namespace, cross-session read/write is denied by default, and all
boundary violations are logged.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

SCHEMA_VERSION = "1.0.0"


class AccessType(Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class SessionRecord:
    """Immutable session identity."""
    session_id: str
    persona_id: str
    namespace: str
    created_at: str  # ISO timestamp

    def __post_init__(self):
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if not self.persona_id:
            raise ValueError("persona_id must be non-empty")
        if not self.namespace:
            raise ValueError("namespace must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "namespace": self.namespace,
            "created_at": self.created_at,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class SessionBoundaryPolicy:
    """Enforces strict session isolation boundaries.

    Each session operates in its own namespace. Cross-session access
    (both read and write) is denied by default with no override mechanism.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionRecord] = {}
        self._audit_log: List[dict] = []

    def register_session(self, session: SessionRecord) -> None:
        if session.session_id in self._sessions:
            existing = self._sessions[session.session_id]
            if existing.namespace != session.namespace:
                raise ValueError(
                    f"Session {session.session_id} already registered with "
                    f"namespace {existing.namespace}"
                )
            return  # idempotent
        self._sessions[session.session_id] = session
        self._audit_log.append({
            "action": "register_session",
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "namespace": session.namespace,
        })

    def check_access(self, requester_session_id: str, target_session_id: str,
                     access_type: AccessType) -> bool:
        """Check if requester session can access target session's data.

        Same-session access is always allowed.
        Cross-session access is always denied (no override).
        """
        if requester_session_id == target_session_id:
            return True

        # Cross-session access is unconditionally denied
        self._audit_log.append({
            "action": "cross_session_denied",
            "requester": requester_session_id,
            "target": target_session_id,
            "access_type": access_type.value,
            "reason": "cross_session_access_prohibited",
        })
        return False

    def check_write(self, session_id: str, target_namespace: str) -> bool:
        """Check if session can write to target namespace.

        A session can only write to its own namespace.
        """
        session = self._sessions.get(session_id)
        if not session:
            self._audit_log.append({
                "action": "write_denied",
                "session_id": session_id,
                "target_namespace": target_namespace,
                "reason": "session_not_registered",
            })
            return False

        allowed = session.namespace == target_namespace
        if not allowed:
            self._audit_log.append({
                "action": "write_denied",
                "session_id": session_id,
                "target_namespace": target_namespace,
                "reason": "namespace_mismatch",
            })
        return allowed

    def check_read(self, session_id: str, target_namespace: str) -> bool:
        """Check if session can read from target namespace.

        A session can only read from its own namespace.
        """
        session = self._sessions.get(session_id)
        if not session:
            self._audit_log.append({
                "action": "read_denied",
                "session_id": session_id,
                "target_namespace": target_namespace,
                "reason": "session_not_registered",
            })
            return False

        allowed = session.namespace == target_namespace
        if not allowed:
            self._audit_log.append({
                "action": "read_denied",
                "session_id": session_id,
                "target_namespace": target_namespace,
                "reason": "namespace_mismatch",
            })
        return allowed

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return self._sessions.get(session_id)

    @property
    def audit_log(self) -> List[dict]:
        return list(self._audit_log)

    @property
    def session_count(self) -> int:
        return len(self._sessions)
