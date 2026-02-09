"""
Model Router - Budget Guard

Enforces context-token and latency-budget constraints before dispatch.
Designed to plug into the RoutingEngine as the ``check_budget`` callback.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.profiles import ReasonCode, RoutingProfile

logger = logging.getLogger("model-router.budget-guard")


# ---------------------------------------------------------------------------
# Per-backend capacity metadata (populated at startup / config reload)
# ---------------------------------------------------------------------------

@dataclass
class BackendCapacity:
    """Known capacity limits for a backend."""
    backend: str
    max_context: int = 8_000
    avg_latency_ms: float = 1_000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "max_context": self.max_context,
            "avg_latency_ms": self.avg_latency_ms,
        }


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------

class BudgetGuard:
    """
    Stateless budget enforcer.

    Given a backend and the requesting profile, returns ``None`` if the
    backend is within budget, or a ``ReasonCode`` explaining why not.

    Context budget:
        If the profile's ``max_context`` exceeds the backend's known
        ``max_context``, returns BUDGET_EXCEEDED_CONTEXT.

    Latency budget:
        If the backend's ``avg_latency_ms`` exceeds the profile's
        ``latency_ms``, returns BUDGET_EXCEEDED_LATENCY.
    """

    def __init__(self, capacities: Optional[Dict[str, BackendCapacity]] = None):
        self._capacities: Dict[str, BackendCapacity] = capacities or {}
        self._check_log: List[Dict[str, Any]] = []

    # ---- configuration ----------------------------------------------------

    def register_backend(self, backend: str, max_context: int = 8_000,
                         avg_latency_ms: float = 1_000.0) -> None:
        """Register or update capacity metadata for a backend."""
        self._capacities[backend] = BackendCapacity(
            backend=backend,
            max_context=max_context,
            avg_latency_ms=avg_latency_ms,
        )

    def update_latency(self, backend: str, observed_ms: float) -> None:
        """Update the rolling average latency for a backend (EWMA)."""
        cap = self._capacities.get(backend)
        if cap is None:
            return
        alpha = 0.3
        cap.avg_latency_ms = alpha * observed_ms + (1 - alpha) * cap.avg_latency_ms

    # ---- core check -------------------------------------------------------

    def check(self, backend: str, profile: RoutingProfile) -> Optional[ReasonCode]:
        """
        Return ``None`` if the backend is within the profile's budget,
        otherwise return a ``ReasonCode``.
        """
        cap = self._capacities.get(backend)
        if cap is None:
            # Unknown backend -- allow (no data to judge)
            return None

        # Context ceiling
        if profile.max_context > cap.max_context:
            reason = ReasonCode.BUDGET_EXCEEDED_CONTEXT
            self._log(backend, profile, reason)
            return reason

        # Latency ceiling
        if cap.avg_latency_ms > profile.latency_ms:
            reason = ReasonCode.BUDGET_EXCEEDED_LATENCY
            self._log(backend, profile, reason)
            return reason

        return None

    # ---- diagnostics ------------------------------------------------------

    def _log(self, backend: str, profile: RoutingProfile, reason: ReasonCode) -> None:
        entry = {
            "backend": backend,
            "profile": profile.name.value,
            "reason": reason.value,
            "timestamp": time.time(),
        }
        self._check_log.append(entry)
        if len(self._check_log) > 200:
            self._check_log = self._check_log[-100:]
        logger.debug("budget: %s rejected for %s (%s)",
                     backend, profile.name.value, reason.value)

    @property
    def recent_rejections(self) -> List[Dict[str, Any]]:
        return list(self._check_log)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capacities": {b: c.to_dict() for b, c in self._capacities.items()},
            "recent_rejections": len(self._check_log),
        }
