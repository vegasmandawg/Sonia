"""
API Gateway — Session Routes (Stage 3)
POST /v1/sessions, GET /v1/sessions/{id}, DELETE /v1/sessions/{id}
"""

import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from session_manager import Session, SessionManager
from jsonl_logger import session_log

logger = logging.getLogger("api-gateway.routes.sessions")


async def handle_create_session(
    user_id: str,
    conversation_id: str,
    profile: str,
    metadata: Dict[str, Any],
    session_mgr: SessionManager,
    correlation_id: str,
) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        sess = await session_mgr.create(
            user_id=user_id,
            conversation_id=conversation_id,
            profile=profile,
            metadata=metadata,
        )
        elapsed = (time.monotonic() - t0) * 1000
        session_log.log({
            "event": "created",
            "session_id": sess.session_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "correlation_id": correlation_id,
            "duration_ms": round(elapsed, 1),
        })
        return {
            "ok": True,
            "session_id": sess.session_id,
            "created_at": sess.created_at,
            "expires_at": sess.expires_at,
            "status": sess.status,
        }
    except RuntimeError as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "ok": False,
            "error": {"code": "MAX_SESSIONS", "message": str(exc), "retryable": True},
        }


async def handle_get_session(
    session_id: str,
    session_mgr: SessionManager,
) -> Dict[str, Any]:
    sess = await session_mgr.get(session_id)
    if not sess:
        return {
            "ok": False,
            "error": {"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found", "retryable": False},
        }
    return {"ok": True, **sess.to_dict()}


async def handle_delete_session(
    session_id: str,
    session_mgr: SessionManager,
    correlation_id: str,
) -> Dict[str, Any]:
    sess = await session_mgr.delete(session_id)
    if not sess:
        return {
            "ok": False,
            "error": {"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found", "retryable": False},
        }
    session_log.log({
        "event": "closed",
        "session_id": session_id,
        "correlation_id": correlation_id,
    })
    return {
        "ok": True,
        "session_id": session_id,
        "closed_at": sess.last_activity,
    }
