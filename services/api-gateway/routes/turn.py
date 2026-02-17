"""
API Gateway - Turn Route (Stage 2 + Stage 4)
Full end-to-end turn pipeline: memory recall -> model generate -> tool exec -> memory write.
Adds quality annotations, response policy, memory write policy, and latency breakdown.
"""

import time
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from schemas.turn import TurnRequest, TurnResponse, TurnRecord, ToolCallRecord, MemorySummary
from turn_quality import (
    normalize_response,
    enforce_non_empty,
    should_use_fallback,
    build_annotations,
    DEFAULT_POLICY,
)
from memory_policy import write_turn_memories, retrieve_context
from schemas.vision import LatencyBreakdown, ResponsePolicy
from jsonl_logger import error_log

logger = logging.getLogger("api-gateway.turn")

# Tools that openclaw actually implements (discovered from /tools)
OPENCLAW_TOOL_ALLOWLIST = frozenset({"shell.run", "file.read", "file.write", "browser.open"})


async def handle_turn(
    request: TurnRequest,
    memory_client: MemoryClient,
    router_client: RouterClient,
    openclaw_client: OpenclawClient,
    correlation_id: str,
) -> TurnResponse:
    """
    Execute a full conversational turn.

    Steps:
    1. Generate turn_id
    2. Query memory-engine for relevant context
    3. Call model-router /chat with context + input
    4. (Optional) Execute tool calls via openclaw
    5. Write turn record to memory-engine (conflict-safe)
    6. Return structured response with quality annotations + latency
    """
    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    turn_id = f"turn_{uuid.uuid4().hex[:16]}"
    response_policy = DEFAULT_POLICY

    retrieved_count = 0
    memory_written = False
    assistant_text = ""
    tool_call_records: List[ToolCallRecord] = []
    tool_result_dicts: List[Dict[str, Any]] = []
    latency = LatencyBreakdown()
    profile_used = response_policy.primary_profile
    fallback_used = False
    completion_reason = "ok"
    tool_calls_attempted = 0
    tool_calls_executed = 0

    try:
        # ── 1. Memory recall ────────────────────────────────────────────
        tm0 = time.monotonic()
        context_text = ""
        try:
            search_resp = await memory_client.search(
                query=request.input_text,
                limit=5,
                correlation_id=correlation_id,
            )
            memories = search_resp.get("results", []) or search_resp.get("memories", [])
            retrieved_count = len(memories)
            if memories:
                context_parts = [m.get("content", "") for m in memories if m.get("content")]
                if context_parts:
                    context_text = "\n".join(context_parts)
        except MemoryClientError as exc:
            logger.warning("memory recall failed (non-fatal): %s", exc)
        latency.memory_read_ms = round((time.monotonic() - tm0) * 1000, 1)

        # ── 2. Build messages for model-router ──────────────────────────
        messages: List[Dict[str, str]] = []
        if context_text:
            messages.append({
                "role": "system",
                "content": f"Relevant context from memory:\n{context_text}",
            })
        messages.append({
            "role": "user",
            "content": request.input_text,
        })

        # ── 3. Call model-router /chat (with fallback) ────────────────
        tmod0 = time.monotonic()
        try:
            chat_resp = await router_client.chat(
                messages=messages,
                correlation_id=correlation_id,
            )
            assistant_text = chat_resp.get("response", "") or ""
            if not assistant_text:
                assistant_text = chat_resp.get("text", "") or chat_resp.get("content", "") or ""
        except RouterClientError as exc:
            if should_use_fallback(True, response_policy):
                try:
                    chat_resp = await router_client.chat(
                        messages=messages,
                        task_type="text",
                        correlation_id=correlation_id,
                    )
                    assistant_text = chat_resp.get("response", "") or chat_resp.get("text", "") or ""
                    fallback_used = True
                    profile_used = response_policy.fallback_profile
                    completion_reason = "fallback"
                except RouterClientError as exc2:
                    latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)
                    latency.total_ms = round((time.monotonic() - t0) * 1000, 1)
                    return TurnResponse(
                        ok=False,
                        turn_id=turn_id,
                        assistant_text="",
                        memory=MemorySummary(written=False, retrieved_count=retrieved_count),
                        duration_ms=latency.total_ms,
                        error={"code": exc2.code, "message": exc2.message},
                    )
            else:
                latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)
                latency.total_ms = round((time.monotonic() - t0) * 1000, 1)
                return TurnResponse(
                    ok=False,
                    turn_id=turn_id,
                    assistant_text="",
                    memory=MemorySummary(written=False, retrieved_count=retrieved_count),
                    duration_ms=latency.total_ms,
                    error={"code": exc.code, "message": exc.message},
                )
        latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)

        # ── 3b. Response normalization ────────────────────────────────
        assistant_text = normalize_response(assistant_text, response_policy)
        assistant_text = enforce_non_empty(assistant_text, response_policy)

        # ── 4. Tool call detection + openclaw routing ─────────────────
        ttool0 = time.monotonic()
        raw_tool_calls = chat_resp.get("tool_calls") or []
        tool_calls_attempted = len(raw_tool_calls)
        capped = raw_tool_calls[:response_policy.max_tool_calls_per_turn]

        for tc in capped:
            tool_name = tc.get("tool_name", tc.get("name", ""))
            tool_args = tc.get("args", tc.get("arguments", {}))
            if tool_name not in OPENCLAW_TOOL_ALLOWLIST:
                tool_call_records.append(ToolCallRecord(
                    tool_name=tool_name,
                    args=tool_args,
                    status="rejected_not_in_allowlist",
                ))
                continue
            # Execute via openclaw
            try:
                exec_resp = await openclaw_client.execute(
                    tool_name=tool_name,
                    args=tool_args,
                    timeout_ms=5000,
                    correlation_id=correlation_id,
                )
                tool_call_records.append(ToolCallRecord(
                    tool_name=tool_name,
                    args=tool_args,
                    status=exec_resp.get("status", "unknown"),
                    result=exec_resp.get("result"),
                ))
                tool_result_dicts.append(exec_resp.get("result", {}))
                tool_calls_executed += 1
            except OpenclawClientError as exc:
                tool_call_records.append(ToolCallRecord(
                    tool_name=tool_name,
                    args=tool_args,
                    status="error",
                    result={"error": exc.message},
                ))
        latency.tool_ms = round((time.monotonic() - ttool0) * 1000, 1)

        # ── 5. Write turn record to memory-engine (conflict-safe) ─────
        tmw0 = time.monotonic()
        mem_result = await write_turn_memories(
            memory_client=memory_client,
            turn_id=turn_id,
            session_id="",
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            input_text=request.input_text,
            assistant_text=assistant_text,
            tool_events=[tc.dict() for tc in tool_call_records] if tool_call_records else None,
            correlation_id=correlation_id,
        )
        memory_written = mem_result["written"]
        latency.memory_write_ms = round((time.monotonic() - tmw0) * 1000, 1)

        # ── 6. Return ─────────────────────────────────────────────────
        latency.total_ms = round((time.monotonic() - t0) * 1000, 1)

        quality = build_annotations(
            profile_used=profile_used,
            fallback_used=fallback_used,
            tool_calls_attempted=tool_calls_attempted,
            tool_calls_executed=tool_calls_executed,
            completion_reason=completion_reason,
        )

        resp = TurnResponse(
            ok=True,
            turn_id=turn_id,
            assistant_text=assistant_text,
            tool_calls=tool_call_records if tool_call_records else None,
            tool_results=tool_result_dicts if tool_result_dicts else None,
            memory=MemorySummary(written=memory_written, retrieved_count=retrieved_count),
            duration_ms=latency.total_ms,
        )

        # Attach quality + latency as extra fields via dict
        resp_dict = resp.dict(exclude_none=True)
        resp_dict["quality"] = quality
        resp_dict["latency"] = latency.dict()

        # We return the Pydantic model for backward compat, but the extra
        # fields are added in main.py's dict() serialization.
        # Store them on the object for main.py to access.
        resp._extra_fields = {"quality": quality, "latency": latency.dict()}
        return resp

    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        logger.error("turn pipeline error: %s", exc, exc_info=True)
        return TurnResponse(
            ok=False,
            turn_id=turn_id,
            assistant_text=assistant_text,
            memory=MemorySummary(written=memory_written, retrieved_count=retrieved_count),
            duration_ms=elapsed,
            error={"code": "INTERNAL_ERROR", "message": str(exc)},
        )
