"""Turn router: drives the reducer and dispatches commands.

Wires together:
    - TurnSnapshot + TurnEvent -> reduce_turn -> (snapshot, commands)
    - Command dispatch with idempotency keys
    - Latency instrumentation
    - Cancel registry integration

Command idempotency key: f"{session_id}:{turn_id}:{seq}:{command.name}"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, List, Optional

from .cancel_registry import CancelRegistry
from .latency_metrics import LatencyCollector
from .turn_events import TurnEvent
from .turn_reducer import Command, reduce_turn
from .turn_state import TurnSnapshot, TurnState, make_initial_snapshot


class CommandExecutionLog:
    """Tracks executed commands for idempotency and audit."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._executed: dict[str, dict] = {}  # key -> result

    def has_executed(self, key: str) -> bool:
        with self._lock:
            return key in self._executed

    def record(self, key: str, result: dict) -> None:
        with self._lock:
            self._executed[key] = result

    def get_result(self, key: str) -> Optional[dict]:
        with self._lock:
            return self._executed.get(key)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._executed)

    def command_log(self) -> list[str]:
        """Return sorted list of all executed command keys (for replay hashing)."""
        with self._lock:
            return sorted(self._executed.keys())


class TurnRouter:
    """Drives voice turn lifecycle with deterministic reducer.

    Usage:
        router = TurnRouter()
        router.start_turn("session1", "turn1", "corr1")
        router.ingest(event)
        router.ingest(event)
        snapshot = router.get_snapshot("session1", "turn1")
    """

    def __init__(
        self,
        cancel_registry: Optional[CancelRegistry] = None,
        latency_collector: Optional[LatencyCollector] = None,
    ) -> None:
        self._lock = Lock()
        self._snapshots: dict[tuple[str, str], TurnSnapshot] = {}
        self._event_logs: dict[tuple[str, str], list[TurnEvent]] = {}
        self._command_logs: dict[tuple[str, str], CommandExecutionLog] = {}
        self._cancel_registry = cancel_registry or CancelRegistry()
        self._latency = latency_collector or LatencyCollector()

    def start_turn(self, session_id: str, turn_id: str, correlation_id: str) -> TurnSnapshot:
        """Initialize a new turn at IDLE state."""
        key = (session_id, turn_id)
        snapshot = make_initial_snapshot(session_id, turn_id, correlation_id)
        with self._lock:
            self._snapshots[key] = snapshot
            self._event_logs[key] = []
            self._command_logs[key] = CommandExecutionLog()
        return snapshot

    def ingest(self, event: TurnEvent) -> tuple[TurnSnapshot, list[Command]]:
        """Ingest an event, run reducer, dispatch commands.

        Returns (new_snapshot, commands_emitted).
        Raises ValueError on invariant violations.
        """
        key = (event.session_id, event.turn_id)

        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is None:
                raise ValueError(f"No active turn for {key}")
            cmd_log = self._command_logs[key]

        # Pure reduce
        new_snapshot, commands = reduce_turn(snapshot, event)

        # Record event
        with self._lock:
            self._snapshots[key] = new_snapshot
            self._event_logs[key].append(event)

        # Latency instrumentation
        if event.event_type == "TURN_STARTED":
            self._latency.record_turn_start(
                event.session_id, event.turn_id, event.ts_monotonic_ns
            )
        elif event.event_type in ("MODEL_FIRST_TOKEN", "TTS_STARTED"):
            self._latency.record_first_emit(
                event.session_id, event.turn_id, event.ts_monotonic_ns
            )

        # Cancel registry integration
        if event.event_type == "BARGE_IN_REQUESTED":
            self._cancel_registry.request(event.session_id, event.turn_id)
        elif event.event_type == "CANCEL_ACK":
            self._cancel_registry.consume(event.session_id, event.turn_id)

        # Dispatch commands with idempotency
        executed_cmds = []
        for cmd in commands:
            idem_key = f"{event.session_id}:{event.turn_id}:{event.seq}:{cmd.name}"
            if not cmd_log.has_executed(idem_key):
                cmd_log.record(idem_key, {"args": cmd.args})
                executed_cmds.append(cmd)

        # Finalize latency on terminal
        if new_snapshot.is_terminal:
            self._latency.finalize_turn(event.session_id, event.turn_id)

        return new_snapshot, executed_cmds

    def get_snapshot(self, session_id: str, turn_id: str) -> Optional[TurnSnapshot]:
        """Get current snapshot for a turn."""
        with self._lock:
            return self._snapshots.get((session_id, turn_id))

    def get_event_log(self, session_id: str, turn_id: str) -> list[TurnEvent]:
        """Get recorded events for replay."""
        with self._lock:
            return list(self._event_logs.get((session_id, turn_id), []))

    def get_command_log(self, session_id: str, turn_id: str) -> CommandExecutionLog:
        """Get command execution log for a turn."""
        with self._lock:
            return self._command_logs.get((session_id, turn_id), CommandExecutionLog())

    def replay(self, session_id: str, turn_id: str, correlation_id: str,
               events: list[TurnEvent]) -> TurnSnapshot:
        """Replay a sequence of events to verify determinism (G19).

        Creates a fresh turn and ingests all events. Returns final snapshot.
        """
        self.start_turn(session_id, turn_id, correlation_id)
        snapshot = None
        for event in events:
            snapshot, _ = self.ingest(event)
        return snapshot

    @property
    def latency(self) -> LatencyCollector:
        return self._latency

    @property
    def cancel_registry(self) -> CancelRegistry:
        return self._cancel_registry
