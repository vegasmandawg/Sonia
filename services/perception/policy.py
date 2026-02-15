"""Perception pipeline policy orchestrator.

Wires normalizer -> dedupe -> priority routing -> confirmation batching
with full provenance at every step.

This is the single entry point for processing perception events.
Downstream consumers never see raw events or bypass dedupe/routing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .event_normalizer import EventNormalizer, PerceptionEnvelope
from .dedupe_engine import DedupeEngine, DECISION_ACCEPT, DECISION_COALESCE
from .priority_router import PriorityRouter, PRIORITY_NAMES
from .confirmation_batcher import ConfirmationBatcher, ConfirmationItem
from .provenance_hooks import ProvenanceChain


@dataclass
class ProcessResult:
    """Result of processing a single raw perception event."""
    envelope: PerceptionEnvelope
    dedupe_decision: str                  # DROP_DUPLICATE | COALESCE | ACCEPT
    priority: Optional[int] = None
    confirmation_item: Optional[ConfirmationItem] = None
    throttled: bool = False
    throttle_reason: Optional[str] = None


class PerceptionPipeline:
    """Full perception pipeline with provenance.

    Flow: normalize -> dedupe -> route -> batch for confirmation
    Every step emits provenance records.
    """

    def __init__(
        self,
        dedupe_window: int = 100,
        lane_cap: int = 50,
        total_cap: int = 150,
        max_pending: int = 50,
        batch_ttl_events: int = 20,
        max_batch_size: int = 10,
    ):
        self.normalizer = EventNormalizer()
        self.dedupe = DedupeEngine(window_size=dedupe_window)
        self.router = PriorityRouter(lane_cap=lane_cap, total_cap=total_cap)
        self.batcher = ConfirmationBatcher(
            max_pending=max_pending,
            batch_ttl_events=batch_ttl_events,
            max_batch_size=max_batch_size,
        )
        self.provenance = ProvenanceChain()

    def process_raw(
        self,
        raw_event: Dict[str, Any],
        action: str = "",
    ) -> ProcessResult:
        """Process a single raw perception event through the full pipeline.

        Steps:
            1. Normalize to canonical envelope
            2. Evaluate dedupe
            3. If accepted/coalesced: route to priority lane
            4. If actionable: submit for confirmation batching
            5. Record provenance at every step

        Returns ProcessResult with all decisions.
        """
        # 1. Normalize
        envelope = self.normalizer.normalize(raw_event)

        # 2. Dedupe
        dedupe_decision = self.dedupe.evaluate(envelope)
        self.provenance.record_dedupe(dedupe_decision, envelope.session_id)

        # 3. If dropped, return early
        if dedupe_decision.decision not in (DECISION_ACCEPT, DECISION_COALESCE):
            return ProcessResult(
                envelope=envelope,
                dedupe_decision=dedupe_decision.decision,
            )

        # 4. Route to priority lane
        priority, overflow = self.router.route(envelope)
        self.provenance.record_route(
            envelope.event_id,
            envelope.session_id,
            priority,
            PRIORITY_NAMES[priority],
        )

        if overflow:
            self.provenance.record_overflow(overflow, envelope.session_id)

        # 5. Submit for confirmation if actionable
        effective_action = action or envelope.payload.get("recommended_action", "")
        confirmation_item = None
        throttled = False
        throttle_reason = None

        if effective_action:
            item, t_reason = self.batcher.submit(envelope, priority, effective_action)
            if t_reason:
                throttled = True
                throttle_reason = t_reason
                self.provenance.record_confirm(
                    envelope.event_id,
                    envelope.session_id,
                    "",
                    "THROTTLE",
                    t_reason,
                )
            elif item:
                confirmation_item = item
                self.provenance.record_confirm(
                    envelope.event_id,
                    envelope.session_id,
                    item.item_id,
                    "SUBMIT",
                    "submitted_for_confirmation",
                )

        return ProcessResult(
            envelope=envelope,
            dedupe_decision=dedupe_decision.decision,
            priority=priority,
            confirmation_item=confirmation_item,
            throttled=throttled,
            throttle_reason=throttle_reason,
        )

    def process_scene_analysis(
        self,
        scene: Dict[str, Any],
        session_id: str,
    ) -> List[ProcessResult]:
        """Process a full SceneAnalysis through the pipeline.

        Normalizes to multiple envelopes (entities + summary) and
        processes each through dedupe/routing/confirmation.
        """
        envelopes = self.normalizer.normalize_scene_analysis(scene, session_id)
        results = []
        for env in envelopes:
            # Build raw dict for process_raw
            raw = {
                "event_id": env.event_id,
                "session_id": env.session_id,
                "source": env.source,
                "event_type": env.event_type,
                "object_id": env.object_id,
                "summary": "",  # already hashed
                "confidence": env.confidence,
                "correlation_id": env.correlation_id,
                "timestamp": env.timestamp,
                "payload": env.payload,
            }
            action = env.payload.get("recommended_action", "")
            result = self.process_raw(raw, action=action or "")
            results.append(result)
        return results

    def get_report(self) -> Dict[str, Any]:
        """Generate pipeline report for gate checks."""
        return {
            "dedupe_stats": self.dedupe.stats,
            "router_stats": self.router.stats,
            "batcher_stats": self.batcher.stats,
            "provenance_stats": self.provenance.stats,
            "provenance_hash": self.provenance.deterministic_hash(),
            "false_bypass_count": self.provenance.false_bypass_count(),
            "double_consume_attempts": self.batcher.stats["double_consume_attempts"],
            "bypass_attempts": self.batcher.stats["bypass_attempts"],
            "orphan_token_count": self.batcher.get_orphan_count(),
            "overflow_events": len(self.router.overflow_log),
        }

    def clear(self) -> None:
        """Reset all pipeline state."""
        self.dedupe.clear()
        self.router.clear()
        self.batcher.clear()
        self.provenance.clear()
