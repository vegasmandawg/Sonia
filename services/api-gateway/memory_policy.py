"""
API Gateway — Memory Quality Policy (Stage 4)

Write policy: stores raw transcript + compact summary with typed tags.
Retrieval policy: bounded context with type filters and token budget.
Conflict-safe: memory failures are non-fatal (return memory.written=false).
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
        try:
            resp = await memory_client.store(
                content=content,
                memory_type=mem_type,
                metadata=meta,
                correlation_id=correlation_id,
            )
            if resp.get("status") == "stored":
                result["items_written"] += 1
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
