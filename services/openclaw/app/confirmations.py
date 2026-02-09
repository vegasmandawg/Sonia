"""
OpenClaw -- Confirmation Token Manager

Manages approval tokens for actions classified as CONFIRM by the
policy engine.  Each token:

    - Is bound to a specific (action, args_hash) scope.
    - Has a short TTL (default 120 seconds).
    - Is single-use: consumed on first redemption.
    - Expired or replayed tokens are rejected.
    - Every mint / redeem / expire event is logged with trace_id.

The flow:

    1.  Policy engine returns CONFIRM.
    2.  Caller calls ``mint_token(action, args, trace_id)`` to create
        a pending approval token and present it to the user.
    3.  User approves -> caller calls ``redeem_token(token_id, trace_id)``.
        On success the action may proceed.
    4.  If TTL expires before redemption, the token is invalidated and
        the action is denied.

Thread safety:
    All public methods are synchronous and use a threading.Lock so the
    manager is safe for concurrent use from async handlers via
    ``run_in_executor`` or direct calls (GIL-protected dict ops are
    already atomic, but the lock serialises mint-check-redeem sequences).

Usage:
    mgr = ConfirmationManager(ttl_seconds=120)
    token = mgr.mint_token("file.write", {"path": "S:\\\\tmp\\\\x"}, "t-001")
    # ... present token.token_id and token.summary to user ...
    result = mgr.redeem_token(token.token_id, "t-001")
    if result.accepted:
        # proceed with action
    else:
        # result.reason explains why (expired, already used, not found)
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ===================================================================
# Token States
# ===================================================================

class TokenState(str, Enum):
    """Lifecycle state of a confirmation token."""
    PENDING = "pending"       # waiting for user decision
    APPROVED = "approved"     # user approved, token consumed
    DENIED = "denied"         # user explicitly denied
    EXPIRED = "expired"       # TTL elapsed without decision
    REPLAYED = "replayed"     # attempted reuse after consumption


# ===================================================================
# Data Structures
# ===================================================================

@dataclass
class ConfirmationToken:
    """A single confirmation token."""

    token_id: str
    action: str
    args_hash: str
    summary: str
    state: TokenState = TokenState.PENDING
    created_at: float = field(default_factory=time.monotonic)
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ttl_seconds: float = 120.0
    trace_id: str = ""
    redeemed_at: Optional[float] = None
    decision_trace_id: Optional[str] = None

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "action": self.action,
            "args_hash": self.args_hash,
            "summary": self.summary,
            "state": self.state.value,
            "created_utc": self.created_utc,
            "ttl_seconds": self.ttl_seconds,
            "remaining_seconds": round(self.remaining_seconds, 1),
            "trace_id": self.trace_id,
        }


@dataclass
class RedeemResult:
    """Outcome of a token redemption attempt."""
    accepted: bool
    token_id: str
    reason: str
    state: TokenState
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "token_id": self.token_id,
            "reason": self.reason,
            "state": self.state.value,
            "trace_id": self.trace_id,
        }


# ===================================================================
# Confirmation Manager
# ===================================================================

class ConfirmationManager:
    """
    Manages the lifecycle of confirmation tokens.

    Thread-safe via an internal lock.  All token storage is in-memory;
    tokens are cheap and ephemeral.
    """

    def __init__(self, ttl_seconds: float = 120.0, max_pending: int = 50):
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._tokens: Dict[str, ConfirmationToken] = {}
        self._lock = threading.Lock()
        self._event_log: List[Dict[str, Any]] = []

    # ── minting ────────────────────────────────────────────────────

    def mint_token(
        self,
        action: str,
        args: Dict[str, Any],
        trace_id: str = "",
        ttl_override: Optional[float] = None,
    ) -> ConfirmationToken:
        """
        Create a new pending confirmation token.

        Args:
            action:       The action name (e.g. "file.write").
            args:         The action arguments (used for scope hash).
            trace_id:     Correlation ID for audit.
            ttl_override: Override the default TTL for this token.

        Returns:
            A new ConfirmationToken in PENDING state.
        """
        with self._lock:
            # Garbage-collect expired tokens before minting
            self._gc_expired()

            # Enforce max pending limit
            pending = sum(
                1 for t in self._tokens.values()
                if t.state == TokenState.PENDING
            )
            if pending >= self._max_pending:
                # Expire the oldest pending token
                oldest = min(
                    (t for t in self._tokens.values()
                     if t.state == TokenState.PENDING),
                    key=lambda t: t.created_at,
                )
                oldest.state = TokenState.EXPIRED
                self._log_event("evicted", oldest.token_id, trace_id,
                                reason="max_pending exceeded")

            args_hash = self._hash_args(action, args)
            summary = self._build_summary(action, args)
            ttl = ttl_override if ttl_override is not None else self._ttl

            token = ConfirmationToken(
                token_id=f"ctk_{uuid.uuid4().hex[:16]}",
                action=action,
                args_hash=args_hash,
                summary=summary,
                ttl_seconds=ttl,
                trace_id=trace_id,
            )
            self._tokens[token.token_id] = token
            self._log_event("minted", token.token_id, trace_id,
                            action=action, ttl=ttl)

            logger.info(
                "confirmation: minted  token=%s  action=%s  ttl=%.0fs  trace=%s",
                token.token_id, action, ttl, trace_id,
            )
            return token

    # ── redemption ─────────────────────────────────────────────────

    def redeem_token(
        self,
        token_id: str,
        trace_id: str = "",
    ) -> RedeemResult:
        """
        Attempt to redeem (approve) a confirmation token.

        Returns:
            RedeemResult indicating success or failure with reason.
        """
        with self._lock:
            token = self._tokens.get(token_id)

            if token is None:
                self._log_event("redeem_not_found", token_id, trace_id)
                return RedeemResult(
                    accepted=False,
                    token_id=token_id,
                    reason="Token not found",
                    state=TokenState.EXPIRED,
                    trace_id=trace_id,
                )

            # Already consumed?
            if token.state != TokenState.PENDING:
                prev_state = token.state
                token.state = TokenState.REPLAYED
                self._log_event("redeem_replay", token_id, trace_id,
                                previous_state=prev_state.value)
                logger.warning(
                    "confirmation: replay attempt  token=%s  prev=%s  trace=%s",
                    token_id, prev_state.value, trace_id,
                )
                return RedeemResult(
                    accepted=False,
                    token_id=token_id,
                    reason=f"Token already used (was {prev_state.value})",
                    state=TokenState.REPLAYED,
                    trace_id=trace_id,
                )

            # Expired?
            if token.is_expired:
                token.state = TokenState.EXPIRED
                self._log_event("redeem_expired", token_id, trace_id)
                logger.info(
                    "confirmation: expired on redeem  token=%s  trace=%s",
                    token_id, trace_id,
                )
                return RedeemResult(
                    accepted=False,
                    token_id=token_id,
                    reason="Token expired",
                    state=TokenState.EXPIRED,
                    trace_id=trace_id,
                )

            # Success: consume the token
            token.state = TokenState.APPROVED
            token.redeemed_at = time.monotonic()
            token.decision_trace_id = trace_id
            self._log_event("redeemed", token_id, trace_id,
                            action=token.action)
            logger.info(
                "confirmation: approved  token=%s  action=%s  trace=%s",
                token_id, token.action, trace_id,
            )
            return RedeemResult(
                accepted=True,
                token_id=token_id,
                reason="Approved",
                state=TokenState.APPROVED,
                trace_id=trace_id,
            )

    # ── explicit denial ────────────────────────────────────────────

    def deny_token(
        self,
        token_id: str,
        trace_id: str = "",
        reason: str = "User denied",
    ) -> RedeemResult:
        """
        Explicitly deny a pending token.
        """
        with self._lock:
            token = self._tokens.get(token_id)

            if token is None:
                return RedeemResult(
                    accepted=False,
                    token_id=token_id,
                    reason="Token not found",
                    state=TokenState.EXPIRED,
                    trace_id=trace_id,
                )

            if token.state != TokenState.PENDING:
                return RedeemResult(
                    accepted=False,
                    token_id=token_id,
                    reason=f"Token not pending (was {token.state.value})",
                    state=token.state,
                    trace_id=trace_id,
                )

            token.state = TokenState.DENIED
            token.decision_trace_id = trace_id
            self._log_event("denied", token_id, trace_id,
                            action=token.action, reason=reason)
            logger.info(
                "confirmation: denied  token=%s  action=%s  reason=%s  trace=%s",
                token_id, token.action, reason, trace_id,
            )
            return RedeemResult(
                accepted=False,
                token_id=token_id,
                reason=reason,
                state=TokenState.DENIED,
                trace_id=trace_id,
            )

    # ── queries ────────────────────────────────────────────────────

    def get_token(self, token_id: str) -> Optional[ConfirmationToken]:
        """Look up a token by ID (snapshot, not live reference)."""
        with self._lock:
            return self._tokens.get(token_id)

    def pending_tokens(self) -> List[ConfirmationToken]:
        """Return all currently pending tokens (not expired)."""
        with self._lock:
            self._gc_expired()
            return [
                t for t in self._tokens.values()
                if t.state == TokenState.PENDING
            ]

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(
                1 for t in self._tokens.values()
                if t.state == TokenState.PENDING and not t.is_expired
            )

    @property
    def total_count(self) -> int:
        return len(self._tokens)

    # ── event log ──────────────────────────────────────────────────

    @property
    def event_log(self) -> List[Dict[str, Any]]:
        return list(self._event_log)

    def recent_events(self, n: int = 20) -> List[Dict[str, Any]]:
        return self._event_log[-n:]

    def clear_event_log(self) -> None:
        self._event_log.clear()

    # ── diagnostics ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise manager state for diagnostics."""
        with self._lock:
            states: Dict[str, int] = {}
            for t in self._tokens.values():
                s = t.state.value
                states[s] = states.get(s, 0) + 1
            return {
                "total_tokens": len(self._tokens),
                "pending": states.get("pending", 0),
                "approved": states.get("approved", 0),
                "denied": states.get("denied", 0),
                "expired": states.get("expired", 0),
                "replayed": states.get("replayed", 0),
                "ttl_seconds": self._ttl,
                "max_pending": self._max_pending,
                "event_count": len(self._event_log),
            }

    # ── internals ──────────────────────────────────────────────────

    def _gc_expired(self) -> None:
        """Mark expired PENDING tokens."""
        now = time.monotonic()
        for t in self._tokens.values():
            if t.state == TokenState.PENDING and now > t.expires_at:
                t.state = TokenState.EXPIRED

    @staticmethod
    def _hash_args(action: str, args: Dict[str, Any]) -> str:
        """Compute a scope hash for the action + args."""
        scope = json.dumps({"action": action, "args": args}, sort_keys=True)
        return hashlib.sha256(scope.encode()).hexdigest()[:16]

    @staticmethod
    def _build_summary(action: str, args: Dict[str, Any]) -> str:
        """Build a human-readable one-line summary of the action."""
        parts = [action]
        if "command" in args:
            cmd = str(args["command"])[:60]
            parts.append(f'command="{cmd}"')
        if "path" in args:
            parts.append(f'path="{args["path"]}"')
        if "url" in args:
            parts.append(f'url="{args["url"]}"')
        return " | ".join(parts)

    def _log_event(
        self,
        event_type: str,
        token_id: str,
        trace_id: str,
        **kwargs: Any,
    ) -> None:
        """Append to the internal event log."""
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "token_id": token_id,
            "trace_id": trace_id,
        }
        entry.update(kwargs)
        self._event_log.append(entry)
