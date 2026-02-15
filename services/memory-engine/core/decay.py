"""Memory decay and forgetting strategies."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any
from enum import Enum
import math

logger = logging.getLogger(__name__)


def _parse_iso_utc(timestamp: str) -> datetime:
    """Parse ISO timestamp and normalize to UTC-aware datetime."""
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class DecayStrategy(str, Enum):
    """Memory decay strategies."""
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    THRESHOLD = "threshold"


class MemoryDecay:
    """Implements memory decay and forgetting for memory items."""

    def __init__(
        self,
        strategy: DecayStrategy = DecayStrategy.EXPONENTIAL,
        half_life_days: float = 30.0,
        threshold_score: float = 0.1,
    ):
        """
        Initialize memory decay engine.

        Args:
            strategy: Decay strategy (exponential, linear, threshold)
            half_life_days: Half-life for exponential decay
            threshold_score: Minimum score before forgetting
        """
        self.strategy = strategy
        self.half_life_days = half_life_days
        self.threshold_score = threshold_score
        self.lambda_exp = math.log(2) / half_life_days

    def compute_decay_score(
        self,
        created_time: str,
        access_count: int = 0,
        relevance: float = 1.0,
        current_time: str = None,
    ) -> float:
        """
        Compute decay score for a memory item.

        Score ranges from 0 (forgotten) to 1 (fresh).

        Args:
            created_time: ISO-8601 creation timestamp
            access_count: Number of times accessed
            relevance: Initial relevance score (0-1)
            current_time: Current time (default: now)

        Returns:
            Decay score (0-1)
        """
        try:
            # Parse timestamps
            created = _parse_iso_utc(created_time)
            current = (
                _parse_iso_utc(current_time)
                if current_time
                else datetime.now(timezone.utc)
            )

            age_days = (current - created).total_seconds() / (24 * 3600)

            # Compute base decay based on strategy
            if self.strategy == DecayStrategy.EXPONENTIAL:
                decay = math.exp(-self.lambda_exp * age_days)
            elif self.strategy == DecayStrategy.LINEAR:
                decay = max(0.0, 1.0 - age_days / self.half_life_days)
            elif self.strategy == DecayStrategy.THRESHOLD:
                decay = 1.0 if age_days < self.half_life_days else 0.0
            else:
                decay = 1.0

            # Apply access boost (accessed items fade slower)
            access_boost = min(2.0, 1.0 + access_count * 0.1)
            
            # Apply relevance weight
            final_score = decay * access_boost * relevance

            return max(0.0, min(1.0, final_score))

        except Exception as e:
            logger.error(f"Decay computation failed: {e}")
            return 0.0

    def should_forget(
        self,
        created_time: str,
        access_count: int = 0,
        relevance: float = 1.0,
    ) -> bool:
        """
        Determine if memory item should be forgotten.

        Args:
            created_time: ISO-8601 creation timestamp
            access_count: Number of times accessed
            relevance: Relevance score (0-1)

        Returns:
            True if item should be forgotten
        """
        score = self.compute_decay_score(created_time, access_count, relevance)
        return score < self.threshold_score

    def compute_batch_decay(
        self, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Apply decay to batch of memory items.

        Args:
            items: List of items with created_time, access_count, relevance

        Returns:
            List of items with decay_score added
        """
        decayed = []
        forgotten = []

        for item in items:
            created_time = item.get("created_time") or item.get("timestamp")
            access_count = item.get("access_count", 0)
            relevance = item.get("relevance", 1.0)

            decay_score = self.compute_decay_score(
                created_time, access_count, relevance
            )

            if self.should_forget(created_time, access_count, relevance):
                forgotten.append(item)
            else:
                item["decay_score"] = decay_score
                decayed.append(item)

        logger.info(
            f"Applied decay: {len(decayed)} retained, {len(forgotten)} forgotten"
        )
        return decayed

    def adjust_ranking(
        self,
        results: List[Dict[str, Any]],
        decay_weight: float = 0.2,
    ) -> List[Dict[str, Any]]:
        """
        Adjust search ranking based on decay.

        Recent, frequently-accessed items rank higher.

        Args:
            results: Search results with relevance scores
            decay_weight: Weight of decay adjustment (0-1)

        Returns:
            Results with adjusted relevance scores
        """
        adjusted = []

        for result in results:
            created_time = result.get("created_time") or result.get("timestamp")
            access_count = result.get("access_count", 0)
            original_relevance = result.get("relevance", 1.0)

            decay_score = self.compute_decay_score(
                created_time, access_count, 1.0
            )

            # Adjust relevance: blend original with decay
            adjusted_relevance = (
                (1.0 - decay_weight) * original_relevance +
                decay_weight * decay_score
            )

            result["relevance"] = adjusted_relevance
            result["decay_factor"] = decay_score
            adjusted.append(result)

        return adjusted


class MemoryConsolidation:
    """Consolidate and compress memory over time."""

    @staticmethod
    def consolidate_similar(
        items: List[Dict[str, Any]],
        similarity_threshold: float = 0.9,
    ) -> List[Dict[str, Any]]:
        """
        Consolidate similar memory items.

        Groups similar items together, reducing storage.

        Args:
            items: Memory items
            similarity_threshold: Min similarity to consolidate

        Returns:
            Consolidated items
        """
        if not items:
            return []

        # Simple consolidation: group by event type
        consolidated = {}
        
        for item in items:
            key = item.get("event_type", "unknown")
            if key not in consolidated:
                consolidated[key] = {
                    "event_type": key,
                    "count": 0,
                    "items": [],
                }
            
            consolidated[key]["count"] += 1
            consolidated[key]["items"].append(item)

        result = []
        for group in consolidated.values():
            if group["count"] > 1:
                # Create summary item
                result.append({
                    "event_type": group["event_type"],
                    "count": group["count"],
                    "consolidated": True,
                    "items": group["items"],
                })
            else:
                result.extend(group["items"])

        logger.info(f"Consolidated {len(items)} items to {len(result)}")
        return result

    @staticmethod
    def compress_old_events(
        items: List[Dict[str, Any]],
        days_threshold: int = 30,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Separate old and recent events.

        Old events can be archived separately.

        Args:
            items: Memory items with timestamps
            days_threshold: Items older than this are archived

        Returns:
            Dict with "recent" and "archived" lists
        """
        now = datetime.now(timezone.utc)
        recent = []
        archived = []

        for item in items:
            timestamp = item.get("timestamp")
            if timestamp:
                try:
                    item_time = _parse_iso_utc(timestamp)
                    age_days = (now - item_time).total_seconds() / (24 * 3600)

                    if age_days < days_threshold:
                        recent.append(item)
                    else:
                        archived.append(item)
                except Exception as e:
                    logger.warning(f"Timestamp parse failed: {e}")
                    recent.append(item)
            else:
                recent.append(item)

        logger.info(
            f"Compressed: {len(recent)} recent, {len(archived)} archived"
        )
        return {"recent": recent, "archived": archived}
