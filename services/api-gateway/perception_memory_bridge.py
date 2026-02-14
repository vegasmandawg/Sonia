"""
Perception Memory Bridge -- SONIA v3.0.0 Milestone 4

Converts perception SceneAnalysis output into typed memories (FACT / SYSTEM_STATE)
with provenance tracking and confirmation binding for downstream actions.

Architecture:
  1. PerceptionMemoryBridge.ingest_scene() converts entities + summary into typed FACTs
  2. Recommended actions stored as SYSTEM_STATE with pending_confirmation status
  3. bind_action_confirmation() gates actions through PerceptionActionGate
  4. on_confirmation_resolved() creates version chain entries for audit trail
  5. Provenance tracked via memory-engine /v1/provenance/track endpoint

Key invariants:
  - Every perception-derived memory has source_type="perception" provenance
  - Every recommended action is gated via PerceptionActionGate (no bypass)
  - Confirmation state changes recorded as SYSTEM_STATE versions (immutable trail)
  - valid_from = scene timestamp (business time), valid_until = None (current)
  - Metadata includes scene_id, correlation_id, trigger, model_used
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.perception_bridge")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PerceptionIngestResult:
    """Result of ingesting a perception scene into typed memory."""
    scene_id: str = ""
    memory_ids: List[str] = field(default_factory=list)
    entity_count: int = 0
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    provenance_source: str = "perception"
    correlation_id: str = ""
    confirmation_requirement_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Perception Memory Bridge
# ---------------------------------------------------------------------------

class PerceptionMemoryBridge:
    """Converts perception SceneAnalysis into typed memories with provenance.

    Usage:
        bridge = PerceptionMemoryBridge(memory_client)
        result = await bridge.ingest_scene(scene_analysis, session_id, correlation_id)
    """

    def __init__(self, memory_client, provenance_base_url: Optional[str] = None):
        """
        Args:
            memory_client: MemoryClient instance (async, from api-gateway/clients)
            provenance_base_url: Base URL for memory-engine provenance endpoint.
                If None, provenance tracking calls store_typed metadata only.
        """
        self._memory = memory_client
        self._provenance_url = provenance_base_url

    async def ingest_scene(
        self,
        scene_analysis: Dict[str, Any],
        session_id: str,
        correlation_id: str,
    ) -> PerceptionIngestResult:
        """Convert a SceneAnalysis dict into typed memories.

        Extracts:
          - Each entity -> FACT (subject=label, predicate="detected_in_scene")
          - Scene summary -> FACT (subject=scene_id, predicate="scene_summary")
          - Recommended action -> SYSTEM_STATE (component="perception")

        Args:
            scene_analysis: SceneAnalysis dict from perception service
            session_id: Current session ID
            correlation_id: Trace correlation ID

        Returns:
            PerceptionIngestResult with memory_ids, conflicts, errors
        """
        result = PerceptionIngestResult(
            correlation_id=correlation_id,
        )

        # Validate required scene fields
        scene_id = scene_analysis.get("scene_id", "")
        if not scene_id:
            result.errors.append("scene_analysis missing scene_id")
            return result

        result.scene_id = scene_id
        timestamp = scene_analysis.get("timestamp", "")
        valid_from = timestamp if timestamp else None

        # Common metadata for all perception memories
        base_metadata = {
            "scene_id": scene_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "trigger": scene_analysis.get("trigger", ""),
            "model_used": scene_analysis.get("model_used", ""),
            "inference_ms": scene_analysis.get("inference_ms"),
            "privacy_verified": scene_analysis.get("privacy_verified", False),
            "source_type": "perception",
        }

        # 1. Entity FACTs
        entities = scene_analysis.get("entities", []) or []
        result.entity_count = len(entities)

        for entity in entities:
            label = entity.get("label", "")
            if not label:
                continue

            confidence = entity.get("confidence", 0.5)
            content = json.dumps({
                "subject": label,
                "predicate": "detected_in_scene",
                "object": scene_id,
                "confidence": confidence,
                "source": "perception",
            })

            entity_meta = {
                **base_metadata,
                "entity_attributes": entity.get("attributes", {}),
                "bounding_box": entity.get("bounding_box"),
            }

            resp = await self._write_typed(
                memory_type="fact",
                subtype="FACT",
                content=content,
                metadata=entity_meta,
                valid_from=valid_from,
                correlation_id=correlation_id,
            )

            if resp.get("written"):
                mid = resp["memory_id"]
                result.memory_ids.append(mid)
                # Track provenance
                await self._track_provenance(
                    mid, scene_id, correlation_id,
                    scene_analysis.get("trigger", ""),
                    scene_analysis.get("model_used", ""),
                )
                if resp.get("conflicts"):
                    result.conflicts.extend(resp["conflicts"])
            else:
                result.errors.extend(resp.get("errors", []))

        # 2. Scene summary FACT
        summary = scene_analysis.get("summary", "")
        overall_confidence = scene_analysis.get("overall_confidence", 0.5)
        if summary:
            content = json.dumps({
                "subject": scene_id,
                "predicate": "scene_summary",
                "object": summary,
                "confidence": overall_confidence,
                "source": "perception",
            })

            resp = await self._write_typed(
                memory_type="fact",
                subtype="FACT",
                content=content,
                metadata=base_metadata,
                valid_from=valid_from,
                correlation_id=correlation_id,
            )

            if resp.get("written"):
                mid = resp["memory_id"]
                result.memory_ids.append(mid)
                await self._track_provenance(
                    mid, scene_id, correlation_id,
                    scene_analysis.get("trigger", ""),
                    scene_analysis.get("model_used", ""),
                )
                if resp.get("conflicts"):
                    result.conflicts.extend(resp["conflicts"])
            else:
                result.errors.extend(resp.get("errors", []))

        # 3. Recommended action SYSTEM_STATE
        recommended_action = scene_analysis.get("recommended_action", "")
        if recommended_action:
            content = json.dumps({
                "component": "perception",
                "state_key": "recommended_action",
                "state_value": recommended_action,
                "health_status": "pending_confirmation",
            })

            resp = await self._write_typed(
                memory_type="system",
                subtype="SYSTEM_STATE",
                content=content,
                metadata=base_metadata,
                valid_from=valid_from,
                correlation_id=correlation_id,
            )

            if resp.get("written"):
                mid = resp["memory_id"]
                result.memory_ids.append(mid)
                await self._track_provenance(
                    mid, scene_id, correlation_id,
                    scene_analysis.get("trigger", ""),
                    scene_analysis.get("model_used", ""),
                )
            else:
                result.errors.extend(resp.get("errors", []))

        return result

    async def bind_action_confirmation(
        self,
        scene_analysis: Dict[str, Any],
        gate,
        session_id: str,
        correlation_id: str,
    ):
        """Gate a perception-recommended action through confirmation.

        Args:
            scene_analysis: SceneAnalysis dict
            gate: PerceptionActionGate instance
            session_id: Current session
            correlation_id: Trace ID

        Returns:
            ConfirmationRequirement in PENDING state, or None if no action
        """
        recommended_action = scene_analysis.get("recommended_action", "")
        if not recommended_action:
            return None

        scene_id = scene_analysis.get("scene_id", "")
        action_args = scene_analysis.get("action_args", {})

        # Gate the action
        requirement = gate.require_confirmation(
            action=recommended_action,
            args=action_args,
            scene_id=scene_id,
            session_id=session_id,
            correlation_id=correlation_id,
        )

        # Record the pending confirmation as SYSTEM_STATE
        content = json.dumps({
            "component": "perception_gate",
            "state_key": f"confirmation:{requirement.requirement_id}",
            "state_value": "pending",
            "health_status": "awaiting_approval",
        })

        meta = {
            "scene_id": scene_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "requirement_id": requirement.requirement_id,
            "action": recommended_action,
            "risk_level": requirement.risk_level,
            "source_type": "perception",
        }

        resp = await self._write_typed(
            memory_type="system",
            subtype="SYSTEM_STATE",
            content=content,
            metadata=meta,
            correlation_id=correlation_id,
        )

        if resp.get("written"):
            # Attach the memory_id to the requirement for later versioning
            requirement.confirmation_memory_id = resp["memory_id"]

        return requirement

    async def on_confirmation_resolved(
        self,
        requirement,
        resolution: str,
        correlation_id: str = "",
    ) -> Optional[str]:
        """Record confirmation resolution as a version of the SYSTEM_STATE memory.

        Args:
            requirement: ConfirmationRequirement with confirmation_memory_id
            resolution: "approved" or "denied"
            correlation_id: Trace ID

        Returns:
            New version memory_id, or None on failure
        """
        memory_id = getattr(requirement, "confirmation_memory_id", None)
        if not memory_id:
            logger.warning("No confirmation_memory_id on requirement %s",
                           getattr(requirement, "requirement_id", "?"))
            return None

        new_content = json.dumps({
            "component": "perception_gate",
            "state_key": f"confirmation:{requirement.requirement_id}",
            "state_value": resolution,
            "health_status": "resolved",
        })

        try:
            resp = await self._memory.create_version(
                original_id=memory_id,
                new_content=new_content,
                metadata={"resolution": resolution, "requirement_id": requirement.requirement_id},
                correlation_id=correlation_id,
            )
            return resp.get("id")
        except Exception as exc:
            logger.warning("Failed to version confirmation memory %s: %s", memory_id, exc)
            return None

    # -- Private helpers ---------------------------------------------------

    async def _write_typed(
        self,
        memory_type: str,
        subtype: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        correlation_id: str = "",
    ) -> Dict[str, Any]:
        """Write a typed memory via the memory client. Never raises."""
        result = {"written": False, "memory_id": None, "conflicts": [], "errors": []}
        try:
            resp = await self._memory.store_typed(
                memory_type=memory_type,
                subtype=subtype,
                content=content,
                metadata=metadata,
                valid_from=valid_from,
                valid_until=valid_until,
                correlation_id=correlation_id,
            )
            result["written"] = resp.get("status") == "stored"
            result["memory_id"] = resp.get("id")
            result["conflicts"] = resp.get("conflicts", [])
        except Exception as exc:
            err = str(exc)
            result["errors"].append(err)
            logger.warning("Typed memory write failed: %s", err)
        return result

    async def _track_provenance(
        self,
        memory_id: str,
        scene_id: str,
        correlation_id: str,
        trigger: str,
        model_used: str,
    ) -> None:
        """Track provenance for a perception-derived memory. Best-effort."""
        try:
            if self._provenance_url:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{self._provenance_url}/v1/provenance/track",
                        json={
                            "memory_id": memory_id,
                            "source_type": "perception",
                            "source_id": scene_id,
                            "metadata": {
                                "correlation_id": correlation_id,
                                "trigger": trigger,
                                "model_used": model_used,
                            },
                        },
                    )
        except Exception as exc:
            logger.debug("Provenance tracking best-effort failed: %s", exc)
