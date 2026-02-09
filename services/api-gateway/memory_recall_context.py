"""
v2.8 M2: Auditable Memory Recall Context

Wraps memory_client.search() with full audit trail:
  - query_id for correlation
  - retrieved memory_ids
  - timing information
  - context budget enforcement
  - integration with EventEnvelope for traceability

Usage:
    recall = MemoryRecallContext(memory_client)
    result = await recall.retrieve(query="user's home dir", correlation_id="req_123")
    # result.context_text -> injected into model prompt
    # result.memory_ids -> list of retrieved memory IDs
    # result.query_id -> unique ID for this retrieval event
    # result.elapsed_ms -> retrieval latency
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryRecallResult:
    """Auditable result of a memory retrieval operation."""
    query_id: str = ""
    query_text: str = ""
    context_text: str = ""
    memory_ids: List[str] = field(default_factory=list)
    retrieved_count: int = 0
    used_count: int = 0  # After budget truncation
    truncated: bool = False
    elapsed_ms: float = 0.0
    correlation_id: str = ""
    error: Optional[str] = None

    def to_audit_dict(self) -> Dict[str, Any]:
        """Return audit-friendly dict for event envelope."""
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "retrieved_count": self.retrieved_count,
            "used_count": self.used_count,
            "memory_ids": self.memory_ids,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
            "correlation_id": self.correlation_id,
            "error": self.error,
        }


@dataclass
class MemoryRecallConfig:
    """Configuration for memory retrieval."""
    max_context_chars: int = 2000
    max_results: int = 10
    timeout_ms: float = 5000
    enabled: bool = True


class MemoryRecallContext:
    """
    Auditable memory retrieval layer.

    Wraps memory_client.search() with:
      - Unique query_id per retrieval
      - Memory ID tracking for audit trail
      - Context budget enforcement
      - Latency instrumentation
      - Error isolation (never raises, returns empty result)
    """

    def __init__(
        self,
        memory_client,
        config: Optional[MemoryRecallConfig] = None,
    ):
        self._client = memory_client
        self._config = config or MemoryRecallConfig()
        self._history: List[MemoryRecallResult] = []
        self._max_history = 100

    @property
    def recall_count(self) -> int:
        """Total recall operations performed."""
        return len(self._history)

    @property
    def recent_recalls(self) -> List[MemoryRecallResult]:
        """Last 10 recall results."""
        return self._history[-10:]

    async def retrieve(
        self,
        query: str,
        correlation_id: str = "",
        config_override: Optional[MemoryRecallConfig] = None,
    ) -> MemoryRecallResult:
        """
        Retrieve memory context for a turn.

        Never raises -- returns empty result on error.
        All errors are logged but isolated.

        Args:
            query: The search text (typically user's input)
            correlation_id: Trace ID for this retrieval
            config_override: Optional config to use instead of default

        Returns:
            MemoryRecallResult with context and audit trail
        """
        cfg = config_override or self._config
        query_id = f"mq_{uuid.uuid4().hex[:12]}"
        t0 = time.monotonic()

        result = MemoryRecallResult(
            query_id=query_id,
            query_text=query,
            correlation_id=correlation_id,
        )

        if not cfg.enabled:
            result.elapsed_ms = 0.0
            self._record(result)
            return result

        try:
            timeout_s = cfg.timeout_ms / 1000.0
            search_resp = await asyncio.wait_for(
                self._client.search(
                    query=query,
                    limit=cfg.max_results,
                    correlation_id=correlation_id,
                ),
                timeout=timeout_s,
            )

            # Extract results -- handle various response shapes
            memories = self._extract_memories(search_resp)
            result.retrieved_count = len(memories)

            # Apply context budget
            context_parts = []
            used_ids = []
            total_chars = 0

            for mem in memories:
                content = mem.get("content", "")
                mem_id = mem.get("id", mem.get("memory_id", f"mem_{uuid.uuid4().hex[:8]}"))

                if total_chars + len(content) > cfg.max_context_chars:
                    result.truncated = True
                    # Include partial if room
                    remaining = cfg.max_context_chars - total_chars
                    if remaining > 50:  # Worth including
                        context_parts.append(content[:remaining])
                        used_ids.append(mem_id)
                    break

                context_parts.append(content)
                used_ids.append(mem_id)
                total_chars += len(content)

            result.context_text = "\n---\n".join(context_parts)
            result.memory_ids = used_ids
            result.used_count = len(used_ids)

        except asyncio.TimeoutError:
            result.error = f"Memory retrieval timed out after {cfg.timeout_ms}ms"
            logger.warning("Memory recall timeout query_id=%s", query_id)

        except Exception as e:
            result.error = f"Memory retrieval failed: {e}"
            logger.warning("Memory recall error query_id=%s: %s", query_id, e)

        result.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        self._record(result)
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return memory recall statistics."""
        recent = self._history[-20:]
        ok_recalls = [r for r in recent if r.error is None]
        return {
            "total_recalls": self.recall_count,
            "recent_success_rate": len(ok_recalls) / len(recent) if recent else 0.0,
            "recent_avg_latency_ms": (
                sum(r.elapsed_ms for r in ok_recalls) / len(ok_recalls)
                if ok_recalls else 0.0
            ),
            "recent_avg_results": (
                sum(r.retrieved_count for r in ok_recalls) / len(ok_recalls)
                if ok_recalls else 0.0
            ),
        }

    def _extract_memories(self, search_resp) -> List[Dict[str, Any]]:
        """Extract memory list from various response shapes."""
        if isinstance(search_resp, list):
            return search_resp
        if isinstance(search_resp, dict):
            # Try common keys
            for key in ("results", "memories", "items", "data"):
                if key in search_resp and isinstance(search_resp[key], list):
                    return search_resp[key]
            # If it has 'content', treat as single result
            if "content" in search_resp:
                return [search_resp]
        return []

    def _record(self, result: MemoryRecallResult):
        """Store in history, enforce max."""
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


class TurnMemoryEnvelope:
    """
    Attaches memory audit data to a turn's event envelope.

    Collects:
      - recall result (query, IDs, latency)
      - write results (what was stored after turn)
      - links between recall and model decision

    This is the audit bridge between memory and EventBus.
    """

    def __init__(self, turn_id: str, correlation_id: str):
        self.turn_id = turn_id
        self.correlation_id = correlation_id
        self._recall: Optional[MemoryRecallResult] = None
        self._writes: List[Dict[str, Any]] = []
        self._tool_memory_links: List[Dict[str, Any]] = []

    def attach_recall(self, recall: MemoryRecallResult):
        """Attach the recall result for this turn."""
        self._recall = recall

    def record_write(self, memory_type: str, content_preview: str, memory_id: str = ""):
        """Record a memory write for audit."""
        self._writes.append({
            "memory_type": memory_type,
            "content_preview": content_preview[:80],
            "memory_id": memory_id,
        })

    def record_tool_memory_link(self, tool_name: str, memory_ids: List[str]):
        """Record which memories influenced a tool call."""
        self._tool_memory_links.append({
            "tool_name": tool_name,
            "influenced_by_memory_ids": memory_ids,
        })

    def to_event_payload(self) -> Dict[str, Any]:
        """Return full memory audit payload for event envelope."""
        payload = {
            "turn_id": self.turn_id,
            "correlation_id": self.correlation_id,
        }

        if self._recall:
            payload["recall"] = self._recall.to_audit_dict()

        if self._writes:
            payload["writes"] = self._writes
            payload["write_count"] = len(self._writes)

        if self._tool_memory_links:
            payload["tool_memory_links"] = self._tool_memory_links

        return payload

    @property
    def has_recall(self) -> bool:
        return self._recall is not None

    @property
    def recall_memory_ids(self) -> List[str]:
        if self._recall:
            return self._recall.memory_ids
        return []

    @property
    def write_count(self) -> int:
        return len(self._writes)
