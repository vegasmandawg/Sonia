"""Canonical perception event normalization.

Converts raw perception events (vision, audio, fusion) into a
single canonical PerceptionEnvelope before any policy logic.

Contract:
    envelope = normalize(raw_event)
    - Deterministic: same input always produces same output
    - Complete: all policy-relevant fields populated
    - Stable: dedupe_key derived only from stable fields (no wall-clock jitter)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Source types ──────────────────────────────────────────────────────────

VALID_SOURCES = frozenset({"vision", "audio", "fusion"})

# ── Spatial quantization (for vision dedupe stability) ───────────────────

SPATIAL_GRID_SIZE = 50  # pixels -- quantize bounding boxes to 50px grid


def _quantize_bbox(bbox: Optional[Dict[str, float]]) -> Optional[str]:
    """Quantize bounding box to grid for spatial dedup stability.

    Returns a stable string token like 'x0:y0:x1:y1' with grid-snapped values,
    or None if no bbox.
    """
    if not bbox:
        return None
    g = SPATIAL_GRID_SIZE
    x = int(bbox.get("x", 0) // g) * g
    y = int(bbox.get("y", 0) // g) * g
    w = int(bbox.get("w", bbox.get("width", 0)) // g) * g
    h = int(bbox.get("h", bbox.get("height", 0)) // g) * g
    return f"{x}:{y}:{x+w}:{y+h}"


def _content_hash(text: str) -> str:
    """SHA-256 of normalized text content for semantic dedupe."""
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


# ── Canonical Envelope ───────────────────────────────────────────────────

@dataclass(frozen=True)
class PerceptionEnvelope:
    """Canonical normalized perception event.

    All downstream processing (dedupe, routing, confirmation) operates
    on this type, never on raw events.
    """
    event_id: str
    session_id: str
    source: str                          # vision | audio | fusion
    schema_version: str
    event_type: str                      # scene_analysis | entity_detection | ocr | caption
    correlation_id: str

    # Dedupe-stable fields
    object_id: str                       # entity label or stable hash
    spatial_token: Optional[str]         # quantized bbox (vision only)
    content_hash: str                    # semantic content hash

    # Payload (non-dedupe)
    confidence: float
    payload: Dict[str, Any] = field(default_factory=dict)

    # Original timestamp (informational, NOT used in dedupe key)
    timestamp: float = 0.0

    @property
    def dedupe_key(self) -> str:
        """Deterministic dedupe key from stable fields only.

        Inputs: session_id, source, schema_version, event_type,
        object_id, spatial_token, content_hash.
        No wall-clock or jitter fields.
        """
        parts = [
            self.session_id,
            self.source,
            self.schema_version,
            self.event_type,
            self.object_id,
            self.spatial_token or "",
            self.content_hash,
        ]
        canonical = "|".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Normalizer ───────────────────────────────────────────────────────────

class EventNormalizer:
    """Converts raw perception events to canonical PerceptionEnvelopes.

    Deterministic: same raw event always produces the same envelope.
    """

    SCHEMA_VERSION = "1.0.0"

    def normalize(self, raw: Dict[str, Any]) -> PerceptionEnvelope:
        """Normalize a raw perception event dict into a canonical envelope.

        Required raw fields: event_id, session_id, source, event_type.
        Optional: correlation_id, entities, summary, confidence, bbox, timestamp.
        """
        source = raw.get("source", "unknown")
        if source not in VALID_SOURCES:
            source = "fusion"  # default unknown sources to fusion

        event_type = raw.get("event_type", "scene_analysis")
        object_id = raw.get("object_id", raw.get("label", "unknown"))

        # Spatial token (vision events with bounding boxes)
        bbox = raw.get("bounding_box") or raw.get("bbox")
        spatial_token = _quantize_bbox(bbox) if source == "vision" else None

        # Content hash from summary/text/caption
        text_content = raw.get("summary", raw.get("text", raw.get("caption", "")))
        c_hash = _content_hash(text_content) if text_content else _content_hash(object_id)

        return PerceptionEnvelope(
            event_id=raw.get("event_id", ""),
            session_id=raw.get("session_id", ""),
            source=source,
            schema_version=raw.get("schema_version", self.SCHEMA_VERSION),
            event_type=event_type,
            correlation_id=raw.get("correlation_id", ""),
            object_id=object_id,
            spatial_token=spatial_token,
            content_hash=c_hash,
            confidence=float(raw.get("confidence", raw.get("overall_confidence", 0.0))),
            payload=raw.get("payload", {}),
            timestamp=float(raw.get("timestamp", 0.0)),
        )

    def normalize_scene_analysis(
        self,
        scene: Dict[str, Any],
        session_id: str,
    ) -> List[PerceptionEnvelope]:
        """Normalize a SceneAnalysis into multiple envelopes (one per entity + summary).

        Deterministic: same scene always produces same envelopes in same order.
        """
        envelopes: List[PerceptionEnvelope] = []
        correlation_id = scene.get("correlation_id", "")
        timestamp = float(scene.get("timestamp", 0.0))

        # One envelope per entity
        for entity in scene.get("entities", []):
            bbox = entity.get("bounding_box")
            label = entity.get("label", "unknown")
            raw = {
                "event_id": f"{scene.get('scene_id', '')}:entity:{label}",
                "session_id": session_id,
                "source": "vision",
                "event_type": "entity_detection",
                "object_id": label,
                "bounding_box": bbox,
                "summary": label,
                "confidence": entity.get("confidence", 0.0),
                "correlation_id": correlation_id,
                "timestamp": timestamp,
                "payload": entity.get("attributes", {}),
            }
            envelopes.append(self.normalize(raw))

        # Summary envelope
        summary = scene.get("summary", "")
        if summary:
            raw = {
                "event_id": f"{scene.get('scene_id', '')}:summary",
                "session_id": session_id,
                "source": "vision",
                "event_type": "scene_analysis",
                "object_id": scene.get("scene_id", ""),
                "summary": summary,
                "confidence": scene.get("overall_confidence", 0.0),
                "correlation_id": correlation_id,
                "timestamp": timestamp,
                "payload": {
                    "recommended_action": scene.get("recommended_action"),
                    "trigger": scene.get("trigger"),
                },
            }
            envelopes.append(self.normalize(raw))

        return envelopes
