"""
Model Router - Deterministic Routing Engine

Selects a backend from the profile's dispatch chain using health state
and budget constraints.  No randomness -- identical inputs always yield
the same selection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from app.profiles import (
    ProfileName,
    ProfileRegistry,
    ReasonCode,
    RoutingProfile,
    classify_request,
)

logger = logging.getLogger("model-router.routing-engine")


# ---------------------------------------------------------------------------
# Route decision
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    """Immutable record of a single routing decision."""
    trace_id: str
    profile_name: str
    selected_backend: Optional[str]
    fallback_chain: List[str]
    reason_code: str
    skipped: List[Dict[str, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "profile_name": self.profile_name,
            "selected_backend": self.selected_backend,
            "fallback_chain": self.fallback_chain,
            "reason_code": self.reason_code,
            "skipped": self.skipped,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Health / budget check interfaces  (injected as callables)
# ---------------------------------------------------------------------------
# The routing engine doesn't own health state or budget state directly.
# Instead it accepts callback functions so those concerns stay in their
# own modules.  Defaults assume everything is healthy/within budget.

def _always_healthy(backend: str) -> bool:
    return True

def _always_within_budget(backend: str, profile: RoutingProfile) -> Optional[ReasonCode]:
    """Return None when within budget, or a ReasonCode explaining why not."""
    return None


# ---------------------------------------------------------------------------
# Routing engine
# ---------------------------------------------------------------------------

class RoutingEngine:
    """
    Deterministic router: given a request profile, walks the dispatch
    chain and selects the first healthy, budget-compliant backend.

    Tie-break is purely positional (first in list wins).
    """

    def __init__(
        self,
        registry: Optional[ProfileRegistry] = None,
        is_healthy: Callable[[str], bool] = _always_healthy,
        check_budget: Callable[[str, RoutingProfile], Optional[ReasonCode]] = _always_within_budget,
    ):
        self._registry = registry or ProfileRegistry()
        self._is_healthy = is_healthy
        self._check_budget = check_budget
        self._decision_log: List[RouteDecision] = []

    # ---- core selection ---------------------------------------------------

    def select(
        self,
        profile_name: ProfileName,
        trace_id: str = "",
        *,
        context_tokens: int = 0,
    ) -> RouteDecision:
        """
        Walk the dispatch chain for *profile_name* and return a RouteDecision.

        The first backend that passes both health and budget checks wins.
        If none qualifies, reason_code is NO_BACKEND_AVAILABLE.
        """
        profile = self._registry.get_or_fallback(profile_name)
        chain = profile.dispatch_chain()
        skipped: List[Dict[str, str]] = []
        selected: Optional[str] = None
        reason = ReasonCode.NO_BACKEND_AVAILABLE

        for backend in chain:
            # --- health gate ---
            if not self._is_healthy(backend):
                skip_reason = ReasonCode.BACKEND_UNHEALTHY
                skipped.append({"backend": backend, "reason": skip_reason.value})
                logger.debug("route: skip %s (%s) trace=%s",
                             backend, skip_reason.value, trace_id)
                continue

            # --- budget gate ---
            budget_fail = self._check_budget(backend, profile)
            if budget_fail is not None:
                skipped.append({"backend": backend, "reason": budget_fail.value})
                logger.debug("route: skip %s (%s) trace=%s",
                             backend, budget_fail.value, trace_id)
                continue

            # --- winner ---
            selected = backend
            if backend in profile.model_prefs:
                reason = ReasonCode.PROFILE_MATCH
            else:
                reason = ReasonCode.FALLBACK_USED
            break

        decision = RouteDecision(
            trace_id=trace_id,
            profile_name=profile.name.value,
            selected_backend=selected,
            fallback_chain=chain,
            reason_code=reason.value,
            skipped=skipped,
        )

        self._decision_log.append(decision)
        if len(self._decision_log) > 500:
            self._decision_log = self._decision_log[-250:]

        if selected:
            logger.info("route: %s -> %s (%s) trace=%s",
                        profile.name.value, selected, reason.value, trace_id)
        else:
            logger.warning("route: %s -> NO BACKEND trace=%s",
                           profile.name.value, trace_id)

        return decision

    # ---- convenience: classify + select -----------------------------------

    def route_request(
        self,
        task_type: str = "",
        hint: str = "",
        trace_id: str = "",
        context_tokens: int = 0,
    ) -> RouteDecision:
        """Classify the request and select a backend in one call."""
        profile_name = classify_request(
            task_type=task_type,
            hint=hint,
            context_tokens=context_tokens,
        )
        return self.select(profile_name, trace_id, context_tokens=context_tokens)

    # ---- diagnostics ------------------------------------------------------

    @property
    def decision_log(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._decision_log]

    @property
    def registry(self) -> ProfileRegistry:
        return self._registry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profiles": self._registry.to_dict(),
            "recent_decisions": len(self._decision_log),
        }
