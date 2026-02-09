"""
Stage 5 M2 — Dead Letter Queue
In-memory dead letter queue for unrecoverable action events.
Supports inspection, replay, and purge operations.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from jsonl_logger import JsonlLogger


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
    """

    def __init__(self):
        self._letters: Dict[str, DeadLetter] = {}
        self._lock = asyncio.Lock()
        self._logger = JsonlLogger("dead_letters")

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
