"""
Pipecat - WebSocket Route Handler
Real-time message handling via WebSocket.
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional, Callable
import asyncio
import json

from sessions import Session, SessionManager, SessionState
from events import (
    Event, MessageEvent, SessionStartEvent, SessionStopEvent,
    StatusEvent, ErrorEvent, EventType
)


async def websocket_handler(
    websocket: WebSocket,
    session_id: str,
    session_manager: SessionManager,
    chat_handler: Optional[Callable] = None,
    correlation_id: str = ""
):
    """
    Handle WebSocket connection for a session.
    
    Flow:
    1. Validate session exists and is ACTIVE
    2. Send SESSION_START event
    3. Listen for MESSAGE events
    4. Forward to chat_handler
    5. Send response back as MESSAGE event
    6. On disconnect or SESSION_STOP, close session
    
    Args:
        websocket: FastAPI WebSocket connection
        session_id: Session ID
        session_manager: SessionManager instance
        chat_handler: Optional async function(message, session_id, correlation_id) -> response
        correlation_id: Correlation ID for tracing
    """
    
    # Validate session exists
    session = session_manager.get(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return
    
    # Validate session is ACTIVE
    if session.state != SessionState.ACTIVE:
        await websocket.close(code=4003, reason=f"Session state is {session.state.value}")
        return
    
    try:
        await websocket.accept()
        
        # Send SESSION_START event
        start_event = SessionStartEvent(
            session_id=session_id,
            metadata=session.metadata,
            correlation_id=correlation_id
        )
        await websocket.send_text(start_event.to_json())
        
        # Send STATUS event - ACTIVE
        status_event = StatusEvent(
            session_id=session_id,
            status="active",
            details={"message": "Session started"},
            correlation_id=correlation_id
        )
        await websocket.send_text(status_event.to_json())
        
        # Listen for messages
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            try:
                # Parse as event
                event = Event.from_json(data)
                
                # Handle MESSAGE event
                if event.type == EventType.MESSAGE:
                    user_message = event.data.get("text", "")
                    
                    # Add to session history
                    session.add_message("user", user_message, event.data.get("metadata"))
                    
                    # Call chat handler if provided
                    response_text = ""
                    if chat_handler:
                        try:
                            # Call handler (could be async call to API Gateway)
                            response_text = await chat_handler(
                                message=user_message,
                                session_id=session_id,
                                correlation_id=event.correlation_id or correlation_id
                            )
                        except Exception as e:
                            # Send error event
                            error_event = ErrorEvent(
                                session_id=session_id,
                                error_code="CHAT_FAILED",
                                error_message=str(e),
                                correlation_id=event.correlation_id or correlation_id
                            )
                            await websocket.send_text(error_event.to_json())
                            continue
                    else:
                        response_text = f"Echo: {user_message}"
                    
                    # Add response to session history
                    session.add_message("assistant", response_text)
                    
                    # Send MESSAGE response
                    response_event = MessageEvent(
                        session_id=session_id,
                        text=response_text,
                        role="assistant",
                        correlation_id=event.correlation_id or correlation_id
                    )
                    await websocket.send_text(response_event.to_json())
                
                # Handle SESSION_STOP event
                elif event.type == EventType.SESSION_STOP:
                    reason = event.data.get("reason", "user_requested")
                    
                    # Send confirmation
                    stop_event = SessionStopEvent(
                        session_id=session_id,
                        reason=reason,
                        correlation_id=event.correlation_id or correlation_id
                    )
                    await websocket.send_text(stop_event.to_json())
                    
                    # Close session
                    session_manager.close(session_id)
                    break
                
                # Handle STATUS event (ping/keepalive)
                elif event.type == EventType.STATUS:
                    status_event = StatusEvent(
                        session_id=session_id,
                        status="active",
                        details={"message_count": len(session.messages)},
                        correlation_id=event.correlation_id or correlation_id
                    )
                    await websocket.send_text(status_event.to_json())
            
            except json.JSONDecodeError:
                error_event = ErrorEvent(
                    session_id=session_id,
                    error_code="INVALID_EVENT",
                    error_message="Failed to parse event as JSON",
                    correlation_id=correlation_id
                )
                await websocket.send_text(error_event.to_json())
            
            except Exception as e:
                error_event = ErrorEvent(
                    session_id=session_id,
                    error_code="INTERNAL_ERROR",
                    error_message=str(e),
                    correlation_id=correlation_id
                )
                await websocket.send_text(error_event.to_json())
    
    except WebSocketDisconnect:
        # Client disconnected
        session_manager.close(session_id)
    
    except Exception as e:
        # Unexpected error
        try:
            error_event = ErrorEvent(
                session_id=session_id,
                error_code="WEBSOCKET_ERROR",
                error_message=str(e),
                correlation_id=correlation_id
            )
            await websocket.send_text(error_event.to_json())
        except:
            pass
        
        session_manager.close(session_id)
