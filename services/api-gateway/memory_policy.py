"""
API Gateway — Memory Quality Policy (Stage 4, v4.3 Epic A outbox)

Write policy: stores raw transcript + compact summary with typed tags.
Retrieval policy: bounded context with type filters and token budget.
Conflict-safe: memory failures are non-fatal (return memory.written=false).

v4.3: Outbox pattern for at-least-once memory write-back.
Memory writes are first enqueued to a durable outbox, then delivered
to memory-engine. Failed deliveries can be retried via flush_outbox().
"""

import json
import logging
from typing import Any, Dict, List, Optional

from clients.memory_client import MemoryClient, MemoryClientError
from jsonl_logger import error_log, turn_log
from schemas.vision import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    MemoryWritePolicy,
    MemoryRetrievalPolicy,
)

logger = logging.getLogger("api-gateway.memory_policy")

DEFAULT_WRITE_POLICY = MemoryWritePolicy()
DEFAULT_RETRIEVAL_POLICY = MemoryRetrievalPolicy()

# v4.3: module-level state store reference for outbox pattern
_outbox_state_store = None


def set_memory_policy_state_store(store) -> None:
    """Inject DurableStateStore for outbox persistence (v4.3 Epic A)."""
    global _outbox_state_store
    _outbox_state_store = store


# ──────────────────────────────────────────────────────────────────────────────
# Write helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_summary(input_text: str, assistant_text: str, max_len: int = 200) -> str:
    """Build a compact summary of a turn for memory storage."""
    user_part = input_text[:80].strip()
    asst_part = assistant_text[:80].strip()
    return f"User: {user_part} | Assistant: {asst_part}"


async def write_turn_memories(
    memory_client: MemoryClient,
    turn_id: str,
    session_id: str,
    user_id: str,
    conversation_id: str,
    input_text: str,
    assistant_text: str,
    vision_summary: Optional[str] = None,
    tool_events: Optional[List[Dict[str, Any]]] = None,
    confirmation_events: Optional[List[Dict[str, Any]]] = None,
    policy: Optional[MemoryWritePolicy] = None,
    correlation_id: str = "",
) -> Dict[str, Any]:
    """
    Write turn data to memory-engine according to policy.

    Returns {"written": bool, "items_written": int, "errors": [...]}.
    Never raises — failures are captured and returned.
    """
    pol = policy or DEFAULT_WRITE_POLICY
    result = {"written": False, "items_written": 0, "errors": []}
    base_meta = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "session_id": session_id,
    }

    async def _store(content: str, mem_type: str, extra_meta: Optional[dict] = None):
        meta = {**base_meta, "type": mem_type}
        if extra_meta:
            meta.update(extra_meta)

        # v4.3: enqueue to outbox before attempting delivery
        outbox_id = None
        if _outbox_state_store:
            try:
                outbox_id = await _outbox_state_store.enqueue_outbox(
                    entry_type=f"turn_memory:{mem_type}",
                    payload={
                        "content": content,
                        "memory_type": mem_type,
                        "metadata": meta,
                        "correlation_id": correlation_id,
                    },
                )
            except Exception as e:
                logger.warning("outbox enqueue failed for %s (non-fatal): %s", mem_type, e)

        try:
            resp = await memory_client.store(
                content=content,
                memory_type=mem_type,
                metadata=meta,
                correlation_id=correlation_id,
            )
            if resp.get("status") == "stored":
                result["items_written"] += 1
                # v4.3: mark outbox entry as delivered
                if _outbox_state_store and outbox_id:
                    try:
                        await _outbox_state_store.mark_delivered(outbox_id)
                    except Exception as e:
                        logger.warning("outbox mark_delivered failed for %s: %s", outbox_id, e)
                return True
        except MemoryClientError as exc:
            err_info = {"type": mem_type, "code": exc.code, "message": exc.message}
            result["errors"].append(err_info)
            error_log.log({
                "session_id": session_id, "turn_id": turn_id,
                "code": "MEMORY_WRITE_FAILED", "detail": err_info,
            })
            logger.warning("memory write failed (%s): %s", mem_type, exc)
        return False

    # Raw turn transcript
    if pol.write_raw:
        raw_content = json.dumps({
            "turn_id": turn_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "input": input_text,
            "output": assistant_text,
        })
        await _store(raw_content, "turn_raw")

    # Compact summary
    if pol.write_summary:
        summary = _build_summary(input_text, assistant_text)
        await _store(summary, "turn_summary")

    # Vision observation
    if pol.include_vision_observation and vision_summary:
        await _store(vision_summary, "vision_observation")

    # Tool events
    if pol.include_tool_events and tool_events:
        for te in tool_events:
            await _store(json.dumps(te, default=str), "tool_event")

    # Confirmation events
    if pol.include_confirmation_events and confirmation_events:
        for ce in confirmation_events:
            await _store(json.dumps(ce, default=str), "confirmation_event")

    result["written"] = result["items_written"] > 0
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Retrieval helpers
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# V3 Retrieval Policy (M3)
# ──────────────────────────────────────────────────────────────────────────────

class MemoryRetrievalPolicyV3:
    """V3 retrieval policy with DB-level budget enforcement."""

    def __init__(
        self,
        use_db_budget: bool = True,
        context_char_budget: int = 7000,
        exclude_redacted: bool = True,
        limit: int = 10,
        type_filters: Optional[List[str]] = None,
    ):
        self.use_db_budget = use_db_budget
        self.context_char_budget = context_char_budget
        self.exclude_redacted = exclude_redacted
        self.limit = limit
        self.type_filters = type_filters


async def write_typed_memory(
    memory_client: "MemoryClient",
    memory_type: str,
    subtype: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    correlation_id: str = "",
) -> Dict[str, Any]:
    """Helper for structured typed memory writes. Never raises."""
    result = {"written": False, "memory_id": None, "conflicts": [], "errors": []}

    # v4.3: enqueue to outbox before attempting delivery
    outbox_id = None
    if _outbox_state_store:
        try:
            outbox_id = await _outbox_state_store.enqueue_outbox(
                entry_type=f"typed_memory:{memory_type}:{subtype}",
                payload={
                    "memory_type": memory_type,
                    "subtype": subtype,
                    "content": content,
                    "metadata": metadata,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "correlation_id": correlation_id,
                },
            )
        except Exception as e:
            logger.warning("outbox enqueue failed for typed %s:%s (non-fatal): %s", memory_type, subtype, e)

    try:
        resp = await memory_client.store_typed(
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

        # v4.3: mark outbox entry as delivered on success
        if result["written"] and _outbox_state_store and outbox_id:
            try:
                await _outbox_state_store.mark_delivered(outbox_id)
            except Exception as e:
                logger.warning("outbox mark_delivered failed for %s: %s", outbox_id, e)
    except MemoryClientError as exc:
        result["errors"].append({"code": exc.code, "message": exc.message})
        logger.warning("typed memory write failed: %s", exc)
    return result


async def retrieve_context(
    memory_client: MemoryClient,
    query: str,
    policy: Optional[MemoryRetrievalPolicy] = None,
    correlation_id: str = "",
) -> Dict[str, Any]:
    """
    Retrieve context from memory within the token budget.

    Returns {
        "context_text": str,
        "retrieved_count": int,
        "truncated": bool,
    }
    """
    pol = policy or DEFAULT_RETRIEVAL_POLICY
    out = {"context_text": "", "retrieved_count": 0, "truncated": False}

    try:
        search_resp = await memory_client.search(
            query=query,
            limit=pol.limit,
            correlation_id=correlation_id,
        )
        memories = search_resp.get("results", []) or search_resp.get("memories", [])
        out["retrieved_count"] = len(memories)

        if not memories:
            return out

        # Build context respecting token budget
        parts: List[str] = []
        char_budget = pol.context_token_budget
        used = 0
        for m in memories:
            content = m.get("content", "")
            if not content:
                continue
            if used + len(content) > char_budget:
                # Add partial if there's room
                remaining = char_budget - used
                if remaining > 50:
                    parts.append(content[:remaining])
                    out["truncated"] = True
                break
            parts.append(content)
            used += len(content)

        out["context_text"] = "\n".join(parts)
    except MemoryClientError as exc:
        logger.warning("memory retrieval failed (non-fatal): %s", exc)

    return out


# ──────────────────────────────────────────────────────────────────────────────
# v4.3: Outbox flush (at-least-once delivery retry)
# ──────────────────────────────────────────────────────────────────────────────

MAX_OUTBOX_RETRY_ATTEMPTS = 5


async def flush_outbox(
    memory_client: MemoryClient,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Retry undelivered outbox entries (at-least-once delivery).
    Reads pending entries from DurableStateStore, attempts memory write,
    marks delivered on success. Skips entries that exceed max retry attempts.

    Returns {"flushed": int, "failed": int, "skipped": int}.
    """
    if not _outbox_state_store:
        return {"flushed": 0, "failed": 0, "skipped": 0}

    result = {"flushed": 0, "failed": 0, "skipped": 0}

    try:
        pending = await _outbox_state_store.get_pending_outbox(limit=limit)
    except Exception as e:
        logger.warning("flush_outbox: failed to load pending entries: %s", e)
        return result

    for entry in pending:
        outbox_id = entry.get("outbox_id", "")
        attempts = entry.get("attempts", 0)
        entry_type = entry.get("entry_type", "")
        payload = entry.get("payload", {})

        if attempts >= MAX_OUTBOX_RETRY_ATTEMPTS:
            result["skipped"] += 1
            continue

        try:
            if entry_type.startswith("turn_memory:"):
                # Re-attempt turn memory store
                resp = await memory_client.store(
                    content=payload.get("content", ""),
                    memory_type=payload.get("memory_type", ""),
                    metadata=payload.get("metadata", {}),
                    correlation_id=payload.get("correlation_id", ""),
                )
                if resp.get("status") == "stored":
                    await _outbox_state_store.mark_delivered(outbox_id)
                    result["flushed"] += 1
                else:
                    await _outbox_state_store.increment_attempt(outbox_id)
                    result["failed"] += 1
            elif entry_type.startswith("typed_memory:"):
                # Re-attempt typed memory store
                resp = await memory_client.store_typed(
                    memory_type=payload.get("memory_type", ""),
                    subtype=payload.get("subtype", ""),
                    content=payload.get("content", ""),
                    metadata=payload.get("metadata"),
                    valid_from=payload.get("valid_from"),
                    valid_until=payload.get("valid_until"),
                    correlation_id=payload.get("correlation_id", ""),
                )
                if resp.get("status") == "stored":
                    await _outbox_state_store.mark_delivered(outbox_id)
                    result["flushed"] += 1
                else:
                    await _outbox_state_store.increment_attempt(outbox_id)
                    result["failed"] += 1
            else:
                # Unknown entry type, skip
                logger.warning("flush_outbox: unknown entry type '%s', skipping %s", entry_type, outbox_id)
                result["skipped"] += 1
        except MemoryClientError as exc:
            logger.warning("flush_outbox: delivery failed for %s: %s", outbox_id, exc)
            try:
                await _outbox_state_store.increment_attempt(outbox_id)
            except Exception:
                pass
            result["failed"] += 1
        except Exception as exc:
            logger.warning("flush_outbox: unexpected error for %s: %s", outbox_id, exc)
            try:
                await _outbox_state_store.increment_attempt(outbox_id)
            except Exception:
                pass
            result["failed"] += 1

    if result["flushed"] > 0 or result["failed"] > 0:
        logger.info(
            "flush_outbox complete: flushed=%d failed=%d skipped=%d",
            result["flushed"], result["failed"], result["skipped"],
        )

    return result
