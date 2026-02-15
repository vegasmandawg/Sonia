"""Zero-frame enforcer for perception pipeline (v3.3 Epic C).

Ensures that when perception is suspended (privacy SUSPENDED state),
absolutely zero frames are processed. Works in conjunction with
PrivacyGate to provide the zero-frame guarantee.

Key invariants:
    - When enforcer is active, process() returns None for ALL inputs
    - Frame counter stays at 0 during enforcement
    - Resuming increments a generation counter (no stale frame replay)
    - All enforcement decisions are auditable
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EnforcementRecord:
    """Record of a zero-frame enforcement decision."""
    event_id: str
    action: str  # "blocked" | "passed" | "rejected_stale"
    generation: int
    timestamp: float


class ZeroFrameEnforcer:
    """Enforces zero-frame guarantee when active.

    Invariants:
        1. When active: ALL frames are blocked (no exceptions)
        2. Generation counter prevents stale frame replay after resume
        3. Enforcement is non-destructive (frames are blocked, not modified)
        4. Stats are always accurate
    """

    def __init__(self):
        self._active = False
        self._generation = 0
        self._records: List[EnforcementRecord] = []
        self._stats = {
            "frames_blocked": 0,
            "frames_passed": 0,
            "stale_rejected": 0,
            "activations": 0,
            "deactivations": 0,
        }

    @property
    def active(self) -> bool:
        return self._active

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def activate(self) -> int:
        """Activate zero-frame enforcement.

        Returns the current generation counter.
        """
        if not self._active:
            self._active = True
            self._stats["activations"] += 1
        return self._generation

    def deactivate(self) -> int:
        """Deactivate zero-frame enforcement and bump generation.

        Returns the new generation counter.
        Bumping generation prevents stale frames from being replayed.
        """
        if self._active:
            self._active = False
            self._generation += 1
            self._stats["deactivations"] += 1
        return self._generation

    def process(
        self,
        event_id: str,
        frame_generation: Optional[int] = None,
    ) -> bool:
        """Check if a frame should be processed.

        Args:
            event_id: The perception event ID
            frame_generation: Generation the frame was created in (for replay detection)

        Returns:
            True if frame should be processed, False if blocked.
        """
        if self._active:
            self._stats["frames_blocked"] += 1
            self._records.append(EnforcementRecord(
                event_id=event_id,
                action="blocked",
                generation=self._generation,
                timestamp=time.time(),
            ))
            return False

        # Check for stale frame replay
        if frame_generation is not None and frame_generation < self._generation:
            self._stats["stale_rejected"] += 1
            self._records.append(EnforcementRecord(
                event_id=event_id,
                action="rejected_stale",
                generation=self._generation,
                timestamp=time.time(),
            ))
            return False

        self._stats["frames_passed"] += 1
        self._records.append(EnforcementRecord(
            event_id=event_id,
            action="passed",
            generation=self._generation,
            timestamp=time.time(),
        ))
        return True

    def get_blocked_count(self) -> int:
        """Total frames blocked during current activation."""
        return self._stats["frames_blocked"]

    def get_audit_trail(self) -> List[Dict[str, Any]]:
        """Return audit trail of enforcement decisions."""
        return [
            {
                "event_id": r.event_id,
                "action": r.action,
                "generation": r.generation,
            }
            for r in self._records
        ]
