"""
Stage 5 M2 — Dead Letter Queue (v4.3 Epic A durability)
In-memory dead letter queue for unrecoverable action events.
Supports inspection, replay, purge, and write-through to DurableStateStore.
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from jsonl_logger import JsonlLogger

logger = logging.getLogger("api-gateway.dead_letter")


MAX_DEAD_LETTERS = 1000


@dataclass
class DeadLetter:
    """A single dead letter entry."""
    letter_id: str
    action_id: str
    intent: str
    params: Dict[str, Any]
    error_code: str
    error_message: str
    correlation_id: Optional[str]
    session_id: Optional[str]
    created_at: datetime
    retries_exhausted: int
    failure_class: Optional[str] = None   # Stage 6: retry taxonomy bucket
    replayed: bool = False
    replayed_at: Optional[datetime] = None
    replay_action_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "letter_id": self.letter_id,
            "action_id": self.action_id,
            "intent": self.intent,
            "params": self.params,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "failure_class": self.failure_class,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() + "Z",
            "retries_exhausted": self.retries_exhausted,
            "replayed": self.replayed,
        }
        if self.replayed_at:
            d["replayed_at"] = self.replayed_at.isoformat() + "Z"
        if self.replay_action_id:
            d["replay_action_id"] = self.replay_action_id
        return d


class DeadLetterQueue:
    """
    In-memory dead letter queue for failed actions.
    Thread-safe via asyncio lock. Bounded to MAX_DEAD_LETTERS.
    v4.3: write-through to DurableStateStore for crash recovery.
    """

    def __init__(self):
        self._letters: Dict[str, DeadLetter] = {}
        self._lock = asyncio.Lock()
        self._logger = JsonlLogger("dead_letters")
        self._state_store = None  # v4.3: DurableStateStore

    def set_state_store(self, store) -> None:
        """Inject DurableStateStore for write-through persistence (v4.3 Epic A)."""
        self._state_store = store

    async def restore_dead_letters(self) -> int:
        """Restore dead letters from durable state store on startup. Returns count restored."""
        if not self._state_store:
            return 0
        try:
            records = await self._state_store.load_dead_letters()
            count = 0
            for rec in records:
                created_at_str = rec.get("created_at", "")
                try:
                    if created_at_str.endswith("Z"):
                        created_at_str = created_at_str[:-1]
                    created_at = datetime.fromisoformat(created_at_str)
                except (ValueError, TypeError):
                    created_at = datetime.utcnow()

                replayed_at = None
                replayed_at_str = rec.get("replayed_at")
                if replayed_at_str:
                    try:
                        if replayed_at_str.endswith("Z"):
                            replayed_at_str = replayed_at_str[:-1]
                        replayed_at = datetime.fromisoformat(replayed_at_str)
                    except (ValueError, TypeError):
                        pass

                dl = DeadLetter(
                    letter_id=rec["letter_id"],
                    action_id=rec.get("action_id", ""),
                    intent=rec.get("intent", ""),
                    params=rec.get("params", {}),
                    error_code=rec.get("error_code", ""),
                    error_message=rec.get("error_message", ""),
                    correlation_id=rec.get("correlation_id"),
                    session_id=rec.get("session_id"),
                    created_at=created_at,
                    retries_exhausted=rec.get("retries_exhausted", 0),
                    failure_class=rec.get("failure_class"),
                    replayed=bool(rec.get("replayed", False)),
                    replayed_at=replayed_at,
                    replay_action_id=rec.get("replay_action_id"),
                )
                self._letters[dl.letter_id] = dl
                count += 1
            logger.info("Restored %d dead letters from durable state store", count)
            return count
        except Exception as e:
            logger.warning("Dead letter restore failed (non-fatal): %s", e)
            return 0

    async def enqueue(
        self,
        action_id: str,
        intent: str,
        params: Dict[str, Any],
        error_code: str,
        error_message: str,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retries_exhausted: int = 0,
        failure_class: Optional[str] = None,
    ) -> str:
        """Add a failed action to the dead letter queue. Returns letter_id."""
        async with self._lock:
            letter_id = f"dl_{uuid.uuid4().hex[:12]}"
            dl = DeadLetter(
                letter_id=letter_id,
                action_id=action_id,
                intent=intent,
                params=params,
                error_code=error_code,
                error_message=error_message,
                correlation_id=correlation_id,
                session_id=session_id,
                created_at=datetime.utcnow(),
                retries_exhausted=retries_exhausted,
                failure_class=failure_class,
            )
            self._letters[letter_id] = dl

            # Evict oldest if over limit
            if len(self._letters) > MAX_DEAD_LETTERS:
                oldest_key = min(self._letters, key=lambda k: self._letters[k].created_at)
                self._letters.pop(oldest_key, None)

            self._logger.log({
                "event": "enqueued",
                "letter_id": letter_id,
                "action_id": action_id,
                "intent": intent,
                "error_code": error_code,
                "error_message": error_message,
            })

        # v4.3: write-through to durable state store (best-effort, outside lock)
        if self._state_store:
            try:
                await self._state_store.persist_dead_letter(dl.to_dict())
            except Exception as e:
                logger.warning("Dead letter persist failed for %s: %s", letter_id, e)

        return letter_id

    async def get(self, letter_id: str) -> Optional[DeadLetter]:
        return self._letters.get(letter_id)

    async def list_letters(
        self,
        limit: int = 50,
        offset: int = 0,
        include_replayed: bool = False,
    ) -> List[DeadLetter]:
        letters = list(self._letters.values())
        if not include_replayed:
            letters = [l for l in letters if not l.replayed]
        letters.sort(key=lambda l: l.created_at, reverse=True)
        return letters[offset: offset + limit]

    async def count(self, include_replayed: bool = False) -> int:
        if include_replayed:
            return len(self._letters)
        return sum(1 for l in self._letters.values() if not l.replayed)

    async def mark_replayed(self, letter_id: str, replay_action_id: str):
        """Mark a dead letter as replayed with the new action_id."""
        async with self._lock:
            dl = self._letters.get(letter_id)
            if dl:
                dl.replayed = True
                dl.replayed_at = datetime.utcnow()
                dl.replay_action_id = replay_action_id
                self._logger.log({
                    "event": "replayed",
                    "letter_id": letter_id,
                    "replay_action_id": replay_action_id,
                })

        # v4.3: persist replay status
        if self._state_store and dl:
            try:
                await self._state_store.update_dead_letter(letter_id, {
                    "replayed": True,
                    "replayed_at": dl.replayed_at,
                    "replay_action_id": replay_action_id,
                })
            except Exception as e:
                logger.warning("Dead letter replay persist failed for %s: %s", letter_id, e)

    async def purge(self, older_than_hours: int = 24) -> int:
        """Purge dead letters older than N hours. Returns count purged."""
        async with self._lock:
            now = datetime.utcnow()
            to_remove = []
            for lid, dl in self._letters.items():
                age_hours = (now - dl.created_at).total_seconds() / 3600
                if age_hours > older_than_hours:
                    to_remove.append(lid)
            for lid in to_remove:
                del self._letters[lid]
            if to_remove:
                self._logger.log({
                    "event": "purged",
                    "count": len(to_remove),
                    "older_than_hours": older_than_hours,
                })
            return len(to_remove)


# ── Singleton ────────────────────────────────────────────────────────────────

_dlq: Optional[DeadLetterQueue] = None


def get_dead_letter_queue() -> DeadLetterQueue:
    global _dlq
    if _dlq is None:
        _dlq = DeadLetterQueue()
    return _dlq
