"""Filters for memory queries and results."""

import logging
from typing import Any, Dict, List, Callable

logger = logging.getLogger(__name__)


class MemoryFilter:
    """Filter chains for memory operations."""

    @staticmethod
    def by_entity(entity_id: str) -> Callable:
        """Filter results by entity ID."""
        return lambda item: item.get("entity_id") == entity_id

    @staticmethod
    def by_type(item_type: str) -> Callable:
        """Filter results by type."""
        return lambda item: item.get("type") == item_type

    @staticmethod
    def by_time_range(start: str, end: str) -> Callable:
        """Filter results by time range."""
        return lambda item: start <= item.get("timestamp", "") <= end

    @staticmethod
    def by_score(min_score: float) -> Callable:
        """Filter results by minimum score."""
        return lambda item: item.get("score", 0) >= min_score

    @staticmethod
    def apply_filters(
        items: List[Dict[str, Any]],
        filters: List[Callable],
    ) -> List[Dict[str, Any]]:
        """Apply filter chain to items."""
        result = items
        for filter_func in filters:
            result = [item for item in result if filter_func(item)]
        return result
