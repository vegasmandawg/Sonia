"""
API Gateway — WebSocket Stream Route (Stage 3 + Stage 4 + Stage 7)

WS /v1/stream/{session_id}

Bidirectional event-based streaming with text fallback,
vision ingestion, turn quality controls, memory policy,
latency instrumentation, and end-to-end correlation IDs.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from session_manager import SessionManager
from tool_policy import classify_tool, GatewayConfirmationManager
from jsonl_logger import turn_log, tool_log, error_log
from vision_ingest import validate_frame, VisionIngestError, get_rate_limiter
from turn_quality import (
    normalize_response,
    enforce_non_empty,
    should_use_fallback,
    build_annotations,
    DEFAULT_POLICY,
)
from memory_policy import write_turn_memories, retrieve_context
from schemas.vision import (
    VisionConfig,
    VisionFrame,
    ResponsePolicy,
    LatencyBreakdown,
)

logger = logging.getLogger("api-gateway.routes.stream")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    event_type: str,
    session_id: str = "",
    turn_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "type": event_type,
        "session_id": session_id,
        "turn_id": turn_id,
        "timestamp": _now(),
        "payload": payload or {},
    }


async def handle_stream(
    websocket,
    session_id: str,
    session_mgr: SessionManager,
    memory_client: MemoryClient,
    router_client: RouterClient,
    openclaw_client: OpenclawClient,
    confirmation_mgr: GatewayConfirmationManager,
):
    """
    Main WebSocket handler for /v1/stream/{session_id}.

    Event types handled:
      Client -> Server:
        input.text, input.audio.chunk,
        input.vision.frame, input.vision.snapshot,
        control.vision.enable, control.vision.disable,
        control.end_turn, control.cancel, control.ping
      Server -> Client:
        ack, response.partial, response.final, tool.call.requested,
        tool.call.result, safety.confirmation.required,
        vision.accepted, vision.rejected, vision.summary.final,
        error
    """
    # Validate session
    sess = await session_mgr.get(session_id)
    if not sess or sess.status != "active":
        await websocket.send_json(
            _event("error", session_id, payload={
                "code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} not found or inactive",
                "retryable": False,
            })
        )
        await websocket.close(code=4004)
        return

    await session_mgr.adjust_streams(session_id, +1)

    # Per-session vision config (mutable via control events)
    vision_cfg = VisionConfig(enabled=False)
    # Per-turn response policy
    response_policy = DEFAULT_POLICY

    try:
        # Send ack
        await websocket.send_json(
            _event("ack", session_id, payload={"status": "connected"})
        )

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_json(), timeout=300  # 5 min idle
                )
            except asyncio.TimeoutError:
                await websocket.send_json(
                    _event("error", session_id, payload={
                        "code": "IDLE_TIMEOUT",
                        "message": "No activity for 5 minutes",
                        "retryable": False,
                    })
                )
                break

            event_type = raw.get("type", "")
            payload = raw.get("payload", {})
            turn_id = raw.get("turn_id", "")

            # ── control.ping ────────────────────────────────────────
            if event_type == "control.ping":
                await websocket.send_json(
                    _event("ack", session_id, payload={"pong": True})
                )
                await session_mgr.touch(session_id)
                continue

            # ── control.cancel ──────────────────────────────────────
            if event_type == "control.cancel":
                await websocket.send_json(
                    _event("ack", session_id, turn_id=turn_id, payload={"cancelled": True})
                )
                continue

            # ── control.vision.enable ───────────────────────────────
            if event_type == "control.vision.enable":
                vision_cfg = VisionConfig(
                    enabled=True,
                    max_frame_bytes=payload.get("max_frame_bytes", vision_cfg.max_frame_bytes),
                    max_frames_per_minute=payload.get("max_frames_per_minute", vision_cfg.max_frames_per_minute),
                    max_frames_per_turn=payload.get("max_frames_per_turn", vision_cfg.max_frames_per_turn),
                )
                await websocket.send_json(
                    _event("ack", session_id, payload={
                        "vision_enabled": True,
                        "config": vision_cfg.dict(),
                    })
                )
                continue

            # ── control.vision.disable ──────────────────────────────
            if event_type == "control.vision.disable":
                vision_cfg = VisionConfig(enabled=False)
                await websocket.send_json(
                    _event("ack", session_id, payload={"vision_enabled": False})
                )
                continue

            # ── input.audio.chunk (forward to pipecat WS) ──────────
            if event_type == "input.audio.chunk":
                await websocket.send_json(
                    _event("ack", session_id, turn_id=turn_id, payload={
                        "received": "audio_chunk",
                        "note": "audio relay active when pipecat stream connected",
                    })
                )
                continue

            # ── input.vision.frame / input.vision.snapshot ──────────
            if event_type in ("input.vision.frame", "input.vision.snapshot"):
                frame, err = validate_frame(
                    payload=payload,
                    session_id=session_id,
                    config=vision_cfg,
                    turn_frame_count=0,  # standalone frame outside turn
                )
                if err:
                    await websocket.send_json(
                        _event("vision.rejected", session_id, turn_id=turn_id, payload={
                            "code": err.code,
                            "message": err.message,
                            "frame_id": err.frame_id,
                            "retryable": err.code in ("RATE_LIMIT_EXCEEDED", "TURN_FRAME_LIMIT"),
                        })
                    )
                else:
                    await websocket.send_json(
                        _event("vision.accepted", session_id, turn_id=turn_id, payload={
                            "frame_id": frame.frame_id,
                            "size_bytes": frame.size_bytes,
                            "mime_type": frame.mime_type,
                        })
                    )
                continue

            # ── input.text (with optional vision context) ──────────
            if event_type == "input.text":
                input_text = payload.get("text", "")
                if not input_text:
                    await websocket.send_json(
                        _event("error", session_id, payload={
                            "code": "INVALID_EVENT",
                            "message": "input.text requires payload.text",
                            "retryable": False,
                        })
                    )
                    continue

                turn_id = turn_id or f"turn_{uuid.uuid4().hex[:16]}"
                correlation_id = f"req_{uuid.uuid4().hex[:12]}"
                t0 = time.monotonic()
                latency = LatencyBreakdown()

                await session_mgr.increment_turn(session_id)
                await session_mgr.touch(session_id)

                # Determine if this is a vision turn
                vision_data_b64 = payload.get("vision_data")
                vision_mime = payload.get("vision_mime", "image/png")
                vision_frame: Optional[VisionFrame] = None
                vision_summary_text: Optional[str] = None
                has_vision = bool(vision_data_b64)
                task_type = "text"

                if has_vision:
                    tv0 = time.monotonic()
                    frame, err = validate_frame(
                        payload={
                            "frame_id": f"frm_{uuid.uuid4().hex[:8]}",
                            "mime_type": vision_mime,
                            "data": vision_data_b64,
                        },
                        session_id=session_id,
                        config=vision_cfg if vision_cfg.enabled else VisionConfig(enabled=True),
                        turn_frame_count=0,
                    )
                    if err:
                        await websocket.send_json(
                            _event("vision.rejected", session_id, turn_id=turn_id, payload={
                                "code": err.code,
                                "message": err.message,
                                "frame_id": err.frame_id,
                                "retryable": False,
                            })
                        )
                        # Continue with text-only turn
                        has_vision = False
                    else:
                        vision_frame = frame
                        task_type = "vision"
                        await websocket.send_json(
                            _event("vision.accepted", session_id, turn_id=turn_id, payload={
                                "frame_id": frame.frame_id,
                                "size_bytes": frame.size_bytes,
                            })
                        )
                    latency.vision_ms = round((time.monotonic() - tv0) * 1000, 1)

                # — Memory recall —
                tm0 = time.monotonic()
                mem_ctx = await retrieve_context(
                    memory_client=memory_client,
                    query=input_text,
                    correlation_id=correlation_id,
                )
                retrieved_count = mem_ctx["retrieved_count"]
                context_text = mem_ctx["context_text"]
                latency.memory_read_ms = round((time.monotonic() - tm0) * 1000, 1)

                # — Build messages —
                messages: List[Dict[str, Any]] = []
                if context_text:
                    messages.append({"role": "system", "content": f"Relevant context from memory:\n{context_text}"})
                if has_vision and vision_frame:
                    # Include vision as a user message with image reference
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": input_text},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{vision_frame.mime_type};base64,{vision_frame.data_b64}"
                            }},
                        ],
                    })
                else:
                    messages.append({"role": "user", "content": input_text})

                # — Model call (with fallback) —
                assistant_text = ""
                tool_calls_raw: List[Dict] = []
                profile_used = response_policy.primary_profile
                fallback_used = False
                completion_reason = "ok"

                tmod0 = time.monotonic()
                try:
                    chat_resp = await router_client.chat(
                        messages=messages,
                        task_type=task_type,
                        correlation_id=correlation_id,
                    )
                    assistant_text = chat_resp.get("response", "") or chat_resp.get("text", "") or ""
                    tool_calls_raw = chat_resp.get("tool_calls") or []
                except RouterClientError as exc:
                    if should_use_fallback(True, response_policy):
                        # Try fallback profile
                        try:
                            fallback_messages = [m for m in messages if not (isinstance(m.get("content"), list))]
                            if not fallback_messages:
                                fallback_messages = [{"role": "user", "content": input_text}]
                            chat_resp = await router_client.chat(
                                messages=fallback_messages,
                                task_type="text",
                                correlation_id=correlation_id,
                            )
                            assistant_text = chat_resp.get("response", "") or chat_resp.get("text", "") or ""
                            tool_calls_raw = chat_resp.get("tool_calls") or []
                            fallback_used = True
                            profile_used = response_policy.fallback_profile
                            completion_reason = "fallback"
                        except RouterClientError as exc2:
                            latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)
                            completion_reason = "error"
                            await websocket.send_json(
                                _event("error", session_id, turn_id=turn_id, payload={
                                    "code": exc2.code,
                                    "message": exc2.message,
                                    "retryable": True,
                                })
                            )
                            error_log.log({"session_id": session_id, "turn_id": turn_id, "correlation_id": correlation_id, "code": exc2.code, "message": exc2.message})
                            continue
                    else:
                        latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)
                        completion_reason = "error"
                        await websocket.send_json(
                            _event("error", session_id, turn_id=turn_id, payload={
                                "code": exc.code,
                                "message": exc.message,
                                "retryable": True,
                            })
                        )
                        error_log.log({"session_id": session_id, "turn_id": turn_id, "correlation_id": correlation_id, "code": exc.code, "message": exc.message})
                        continue

                latency.model_ms = round((time.monotonic() - tmod0) * 1000, 1)

                # — Response normalization —
                assistant_text = normalize_response(assistant_text, response_policy)
                assistant_text = enforce_non_empty(assistant_text, response_policy)

                # — Tool calls with safety gate —
                ttool0 = time.monotonic()
                tool_results: List[Dict] = []
                tool_events: List[Dict] = []
                confirmation_events: List[Dict] = []
                tool_calls_attempted = len(tool_calls_raw)
                tool_calls_executed = 0

                # Enforce max tool calls per turn
                capped_tool_calls = tool_calls_raw[:response_policy.max_tool_calls_per_turn]

                for tc in capped_tool_calls:
                    tool_name = tc.get("tool_name", tc.get("name", ""))
                    tool_args = tc.get("args", tc.get("arguments", {}))
                    classification = classify_tool(tool_name)

                    tool_log.log({
                        "session_id": session_id, "turn_id": turn_id,
                        "correlation_id": correlation_id,
                        "tool_name": tool_name, "classification": classification,
                        "disposition": "pending",
                    })

                    if classification == "blocked":
                        await websocket.send_json(
                            _event("tool.call.result", session_id, turn_id=turn_id, payload={
                                "tool_name": tool_name,
                                "status": "blocked",
                                "result": {"error": "Tool is blocked by policy"},
                            })
                        )
                        tool_log.log({
                            "session_id": session_id, "turn_id": turn_id,
                            "correlation_id": correlation_id,
                            "tool_name": tool_name, "disposition": "blocked",
                            "policy_reason": "TOOL_BLOCKED",
                        })
                        tool_events.append({"tool_name": tool_name, "disposition": "blocked"})
                        continue

                    if classification == "guarded_write":
                        token = await confirmation_mgr.create(
                            session_id=session_id,
                            turn_id=turn_id,
                            tool_name=tool_name,
                            args=tool_args,
                        )
                        await websocket.send_json(
                            _event("safety.confirmation.required", session_id, turn_id=turn_id, payload=token.to_dict())
                        )
                        tool_log.log({
                            "session_id": session_id, "turn_id": turn_id,
                            "correlation_id": correlation_id,
                            "tool_name": tool_name, "disposition": "confirmation_required",
                            "confirmation_id": token.confirmation_id,
                        })
                        confirmation_events.append({
                            "confirmation_id": token.confirmation_id,
                            "tool_name": tool_name,
                            "status": "pending",
                        })
                        continue

                    # safe_read — execute immediately
                    try:
                        exec_resp = await openclaw_client.execute(
                            tool_name=tool_name,
                            args=tool_args,
                            timeout_ms=5000,
                            correlation_id=correlation_id,
                        )
                        await websocket.send_json(
                            _event("tool.call.result", session_id, turn_id=turn_id, payload={
                                "tool_name": tool_name,
                                "status": exec_resp.get("status", "unknown"),
                                "result": exec_resp.get("result", {}),
                            })
                        )
                        tool_results.append(exec_resp.get("result", {}))
                        tool_calls_executed += 1
                        tool_log.log({"session_id": session_id, "turn_id": turn_id, "correlation_id": correlation_id, "tool_name": tool_name, "disposition": "executed"})
                        tool_events.append({"tool_name": tool_name, "disposition": "executed"})
                    except OpenclawClientError as exc:
                        await websocket.send_json(
                            _event("tool.call.result", session_id, turn_id=turn_id, payload={
                                "tool_name": tool_name,
                                "status": "error",
                                "result": {"error": exc.message},
                            })
                        )
                        tool_events.append({"tool_name": tool_name, "disposition": "error", "error": exc.message})

                latency.tool_ms = round((time.monotonic() - ttool0) * 1000, 1)

                # — Build quality annotations —
                quality = build_annotations(
                    profile_used=profile_used,
                    fallback_used=fallback_used,
                    tool_calls_attempted=tool_calls_attempted,
                    tool_calls_executed=tool_calls_executed,
                    completion_reason=completion_reason,
                )

                # — Send final response —
                await websocket.send_json(
                    _event("response.final", session_id, turn_id=turn_id, payload={
                        "assistant_text": assistant_text,
                        "memory": {"written": False, "retrieved_count": retrieved_count},
                        "quality": quality,
                        "latency": {},  # placeholder — updated in log
                        "has_vision": has_vision,
                    })
                )

                # — Write turn to memory (conflict-safe) —
                tmw0 = time.monotonic()
                mem_result = await write_turn_memories(
                    memory_client=memory_client,
                    turn_id=turn_id,
                    session_id=session_id,
                    user_id=sess.user_id,
                    conversation_id=sess.conversation_id,
                    input_text=input_text,
                    assistant_text=assistant_text,
                    vision_summary=f"[vision frame: {vision_frame.mime_type} {vision_frame.size_bytes}B]" if vision_frame else None,
                    tool_events=tool_events if tool_events else None,
                    confirmation_events=confirmation_events if confirmation_events else None,
                    correlation_id=correlation_id,
                )
                latency.memory_write_ms = round((time.monotonic() - tmw0) * 1000, 1)

                latency.total_ms = round((time.monotonic() - t0) * 1000, 1)

                turn_log.log({
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "correlation_id": correlation_id,
                    "mode": "stream",
                    "task_type": task_type,
                    "input_len": len(input_text),
                    "output_len": len(assistant_text),
                    "retrieved_count": retrieved_count,
                    "memory_written": mem_result["written"],
                    "memory_items_written": mem_result["items_written"],
                    "has_vision": has_vision,
                    "quality": quality,
                    "latency": latency.dict(),
                    "duration_ms": latency.total_ms,
                })
                continue

            # ── control.end_turn ────────────────────────────────────
            if event_type == "control.end_turn":
                await websocket.send_json(
                    _event("ack", session_id, turn_id=turn_id, payload={"end_turn": True})
                )
                continue

            # ── Unknown event ───────────────────────────────────────
            await websocket.send_json(
                _event("error", session_id, payload={
                    "code": "INVALID_EVENT",
                    "message": f"Unknown event type: {event_type}",
                    "retryable": False,
                })
            )

    except Exception as exc:
        logger.error("stream error session=%s: %s", session_id, exc, exc_info=True)
        error_log.log({"session_id": session_id, "code": "INTERNAL_ERROR", "message": str(exc)})
        try:
            await websocket.send_json(
                _event("error", session_id, payload={
                    "code": "INTERNAL_ERROR",
                    "message": "Internal stream error",
                    "retryable": False,
                })
            )
        except Exception:
            pass
    finally:
        await session_mgr.adjust_streams(session_id, -1)
