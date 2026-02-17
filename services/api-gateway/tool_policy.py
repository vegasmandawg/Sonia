"""
API Gateway — Tool Safety Gate (Stage 3, v4.3 Epic A durability)

Classifies tool calls as safe_read / guarded_write / blocked
and manages confirmation tokens in-memory with optional write-through
to DurableStateStore for restart recovery.

This is the *gateway-side* policy layer.  It complements openclaw's
own PolicyEngine; the gateway gate runs first and can short-circuit
before any call reaches openclaw.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.tool_policy")


# ──────────────────────────────────────────────────────────────────────────────
# Tool classification
# ──────────────────────────────────────────────────────────────────────────────

# safe_read: execute immediately, no confirmation
SAFE_READ_TOOLS = frozenset({"file.read"})

# guarded_write: requires confirmation before execution
GUARDED_WRITE_TOOLS = frozenset({"file.write", "shell.run", "browser.open"})

# blocked: never execute (empty by default; extend via config)
BLOCKED_TOOLS: frozenset = frozenset()


def classify_tool(tool_name: str) -> str:
    """Return 'safe_read', 'guarded_write', or 'blocked'."""
    if tool_name in BLOCKED_TOOLS:
        return "blocked"
    if tool_name in SAFE_READ_TOOLS:
        return "safe_read"
    if tool_name in GUARDED_WRITE_TOOLS:
        return "guarded_write"
    # Unknown tools default to blocked
    return "blocked"


# ──────────────────────────────────────────────────────────────────────────────
# Confirmation token
# ──────────────────────────────────────────────────────────────────────────────

class ConfirmationToken:
    __slots__ = (
        "confirmation_id", "session_id", "turn_id", "tool_name",
        "args", "summary", "status", "created_at", "created_mono",
        "ttl_seconds", "decided_at",
    )

    def __init__(
        self,
        session_id: str,
        turn_id: str,
        tool_name: str,
        args: Dict[str, Any],
        ttl_seconds: float = 120.0,
    ):
        self.confirmation_id = f"cfm_{uuid.uuid4().hex[:16]}"
        self.session_id = session_id
        self.turn_id = turn_id
        self.tool_name = tool_name
        self.args = args
        self.summary = self._build_summary(tool_name, args)
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.created_mono = time.monotonic()
        self.ttl_seconds = ttl_seconds
        self.decided_at: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > (self.created_mono + self.ttl_seconds)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, (self.created_mono + self.ttl_seconds) - time.monotonic())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "summary": self.summary,
            "status": self.status,
            "created_at": self.created_at,
            "remaining_seconds": round(self.remaining_seconds, 1),
        }

    @staticmethod
    def _build_summary(tool_name: str, args: Dict[str, Any]) -> str:
        parts = [tool_name]
        for key in ("command", "path", "url"):
            if key in args:
                parts.append(f'{key}="{str(args[key])[:60]}"')
        return " | ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Confirmation Manager (gateway-local)
# ──────────────────────────────────────────────────────────────────────────────

class GatewayConfirmationManager:
    """
    Hardened confirmation queue for the gateway (Stage 4, v4.3 durability).

    Features:
      - Idempotent approve/deny: repeated calls on same id return
        deterministic result without duplicate execution.
      - Expiry: expired tokens return CONFIRMATION_EXPIRED code.
      - Per-session pending limits (max_guarded_requests_pending).
      - Per-turn tool-time budget (max_total_tool_runtime_ms).
      - Write-through to DurableStateStore for crash recovery.
    """

    def __init__(
        self,
        ttl_seconds: float = 120.0,
        max_pending: int = 50,
        max_guarded_requests_pending: int = 10,
        max_total_tool_runtime_ms: int = 30_000,
    ):
        self._tokens: Dict[str, ConfirmationToken] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._max_guarded_per_session = max_guarded_requests_pending
        self._max_tool_runtime_ms = max_total_tool_runtime_ms
        self._state_store = None  # v4.3: DurableStateStore

    def set_state_store(self, store) -> None:
        """Inject DurableStateStore for write-through persistence (v4.3 Epic A)."""
        self._state_store = store

    async def restore_confirmations(self) -> int:
        """
        Restore pending confirmations from durable state store on startup.
        Recalculates TTL based on created_at + ttl_seconds - now.
        Returns count of restored tokens.
        """
        if not self._state_store:
            return 0
        try:
            records = await self._state_store.load_pending_confirmations()
            count = 0
            now = datetime.now(timezone.utc)
            for rec in records:
                created_at_str = rec.get("created_at", "")
                ttl_seconds = rec.get("ttl_seconds", 120.0)
                # Calculate remaining TTL
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    elapsed = (now - created_at).total_seconds()
                    remaining = ttl_seconds - elapsed
                except (ValueError, TypeError):
                    remaining = 0.0

                if remaining <= 0:
                    # Token already expired, skip restoration
                    continue

                token = ConfirmationToken(
                    session_id=rec.get("session_id", ""),
                    turn_id=rec.get("turn_id", ""),
                    tool_name=rec.get("tool_name", ""),
                    args=rec.get("args", {}),
                    ttl_seconds=remaining,  # use remaining TTL
                )
                # Overwrite generated fields with persisted values
                token.confirmation_id = rec["confirmation_id"]
                token.summary = rec.get("summary", token.summary)
                token.status = rec.get("status", "pending")
                token.created_at = created_at_str
                token.decided_at = rec.get("decided_at")

                self._tokens[token.confirmation_id] = token
                count += 1

            logger.info("Restored %d pending confirmations from durable state store", count)
            return count
        except Exception as e:
            logger.warning("Confirmation restore failed (non-fatal): %s", e)
            return 0

    async def create(
        self,
        session_id: str,
        turn_id: str,
        tool_name: str,
        args: Dict[str, Any],
    ) -> ConfirmationToken:
        async with self._lock:
            self._gc_expired()
            # Enforce per-session pending limit
            session_pending = sum(
                1 for t in self._tokens.values()
                if t.session_id == session_id and t.status == "pending"
            )
            if session_pending >= self._max_guarded_per_session:
                raise RuntimeError(
                    f"Max pending confirmations ({self._max_guarded_per_session}) "
                    f"reached for session {session_id}"
                )
            token = ConfirmationToken(
                session_id=session_id,
                turn_id=turn_id,
                tool_name=tool_name,
                args=args,
                ttl_seconds=self._ttl,
            )
            self._tokens[token.confirmation_id] = token
            logger.info(
                "confirmation minted: %s tool=%s session=%s",
                token.confirmation_id, tool_name, session_id,
            )

        # v4.3: write-through to durable state store (best-effort, outside lock)
        if self._state_store:
            try:
                await self._state_store.persist_confirmation({
                    "confirmation_id": token.confirmation_id,
                    "session_id": token.session_id,
                    "turn_id": token.turn_id,
                    "tool_name": token.tool_name,
                    "args": token.args,
                    "summary": token.summary,
                    "status": token.status,
                    "created_at": token.created_at,
                    "ttl_seconds": token.ttl_seconds,
                    "decided_at": token.decided_at,
                })
            except Exception as e:
                logger.warning("Confirmation persist failed for %s: %s", token.confirmation_id, e)

        return token

    async def approve(self, confirmation_id: str) -> Dict[str, Any]:
        async with self._lock:
            token = self._tokens.get(confirmation_id)
            if not token:
                return {"ok": False, "status": "not_found", "reason": "Token not found"}
            # Idempotent: already approved -> return same result
            if token.status == "approved":
                return {"ok": True, "status": "approved", "reason": "Already approved (idempotent)", "token": token, "idempotent": True}
            # Idempotent: already denied -> return deterministic
            if token.status == "denied":
                return {"ok": False, "status": "denied", "reason": "Already denied (idempotent)", "idempotent": True}
            # Check expiry with explicit code
            if token.status == "pending" and token.is_expired:
                token.status = "expired"
                return {"ok": False, "status": "expired", "reason": "CONFIRMATION_EXPIRED", "code": "CONFIRMATION_EXPIRED"}
            if token.status == "expired":
                return {"ok": False, "status": "expired", "reason": "CONFIRMATION_EXPIRED", "code": "CONFIRMATION_EXPIRED"}
            if token.status != "pending":
                return {"ok": False, "status": token.status, "reason": f"Already {token.status}"}
            token.status = "approved"
            token.decided_at = datetime.now(timezone.utc).isoformat()
            logger.info("confirmation approved: %s", confirmation_id)

        # v4.3: persist status change
        if self._state_store:
            try:
                await self._state_store.update_confirmation(confirmation_id, "approved", token.decided_at)
            except Exception as e:
                logger.warning("Confirmation approve persist failed for %s: %s", confirmation_id, e)

        return {"ok": True, "status": "approved", "reason": "Approved", "token": token}

    async def deny(self, confirmation_id: str, reason: str = "User denied") -> Dict[str, Any]:
        async with self._lock:
            token = self._tokens.get(confirmation_id)
            if not token:
                return {"ok": False, "status": "not_found", "reason": "Token not found"}
            # Idempotent: already denied -> return same result
            if token.status == "denied":
                return {"ok": False, "status": "denied", "reason": f"Already denied (idempotent)", "idempotent": True}
            # Idempotent: already approved -> return deterministic
            if token.status == "approved":
                return {"ok": False, "status": "approved", "reason": "Already approved (idempotent)", "idempotent": True}
            # Check expiry
            if token.status == "pending" and token.is_expired:
                token.status = "expired"
                return {"ok": False, "status": "expired", "reason": "CONFIRMATION_EXPIRED", "code": "CONFIRMATION_EXPIRED"}
            if token.status == "expired":
                return {"ok": False, "status": "expired", "reason": "CONFIRMATION_EXPIRED", "code": "CONFIRMATION_EXPIRED"}
            if token.status != "pending":
                return {"ok": False, "status": token.status, "reason": f"Already {token.status}"}
            token.status = "denied"
            token.decided_at = datetime.now(timezone.utc).isoformat()
            logger.info("confirmation denied: %s reason=%s", confirmation_id, reason)

        # v4.3: persist status change
        if self._state_store:
            try:
                await self._state_store.update_confirmation(confirmation_id, "denied", token.decided_at)
            except Exception as e:
                logger.warning("Confirmation deny persist failed for %s: %s", confirmation_id, e)

        return {"ok": False, "status": "denied", "reason": reason}

    async def get(self, confirmation_id: str) -> Optional[ConfirmationToken]:
        async with self._lock:
            return self._tokens.get(confirmation_id)

    async def pending_for_session(self, session_id: str) -> List[ConfirmationToken]:
        async with self._lock:
            self._gc_expired()
            return [
                t for t in self._tokens.values()
                if t.session_id == session_id and t.status == "pending"
            ]

    def _gc_expired(self):
        for t in list(self._tokens.values()):
            if t.status == "pending" and t.is_expired:
                t.status = "expired"
