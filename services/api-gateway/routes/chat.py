"""
API Gateway - Chat Route
Orchestrates requests to Memory Engine and Model Router.
"""

import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError


async def handle_chat(
    message: str,
    memory_client: MemoryClient,
    router_client: RouterClient,
    session_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    context_limit: int = 10,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle chat request with orchestration to Memory Engine and Model Router.
    
    Flow:
    1. If session_id provided: Query Memory Engine for context
    2. Build prompt with context + user message
    3. Call Model Router to get response
    4. Optionally store result in Memory Engine
    5. Return merged result with provenance
    
    Args:
        message: User message
        memory_client: Memory Engine client
        router_client: Model Router client
        session_id: Optional session ID for context
        correlation_id: Optional correlation ID for tracing
        context_limit: Maximum context items to retrieve
        model: Optional specific model to use
    
    Returns:
        Response dict with standard envelope format
    """
    start_time = time.time()
    
    # Initialize provenance tracking
    provenance = {
        "memory_engine": {"status": "skipped"},
        "model_router": {"status": "pending"}
    }
    
    context = ""
    context_used = False
    
    try:
        # Step 1: Query Memory Engine for context (if session provided)
        if session_id:
            try:
                memory_start = time.time()
                search_result = await memory_client.search(
                    query=message,
                    limit=context_limit,
                    correlation_id=correlation_id
                )
                memory_elapsed = (time.time() - memory_start) * 1000
                
                # Extract context from search results
                if search_result.get("memories"):
                    context_parts = [
                        m.get("content", "") 
                        for m in search_result.get("memories", [])
                        if m.get("content")
                    ]
                    if context_parts:
                        context = "\n".join(context_parts)
                        context_used = True
                
                provenance["memory_engine"] = {
                    "status": "ok",
                    "duration_ms": memory_elapsed,
                    "context_items": len(search_result.get("memories", []))
                }
            
            except MemoryClientError as e:
                # Log but don't fail - continue without context
                provenance["memory_engine"] = {
                    "status": "failed",
                    "error": e.code,
                    "message": e.message
                }
        
        # Step 2: Build prompt with context
        if context:
            full_message = f"Context:\n{context}\n\nUser: {message}"
        else:
            full_message = message
        
        # Step 3: Call Model Router
        router_start = time.time()
        try:
            messages = [
                {
                    "role": "user",
                    "content": full_message
                }
            ]
            
            router_result = await router_client.chat(
                messages=messages,
                model=model,
                correlation_id=correlation_id
            )
            router_elapsed = (time.time() - router_start) * 1000
            
            # Extract response
            response_text = router_result.get("response", "")
            provider = router_result.get("provider", "unknown")
            model_used = router_result.get("model", "unknown")
            
            provenance["model_router"] = {
                "status": "ok",
                "duration_ms": router_elapsed,
                "provider": provider,
                "model": model_used
            }
        
        except RouterClientError as e:
            provenance["model_router"] = {
                "status": "failed",
                "error": e.code,
                "message": e.message
            }
            raise
        
        # Step 4: Optional - store result in Memory Engine
        if session_id and context_used:
            try:
                await memory_client.store(
                    content=response_text,
                    memory_type="conversation_result",
                    metadata={
                        "session_id": session_id,
                        "user_message": message,
                        "provider": provider,
                        "model": model_used
                    },
                    correlation_id=correlation_id
                )
            except MemoryClientError:
                # Store failure is non-critical
                pass
        
        # Step 5: Return merged result
        total_elapsed = (time.time() - start_time) * 1000
        
        return {
            "ok": True,
            "service": "api-gateway",
            "operation": "chat",
            "correlation_id": correlation_id,
            "duration_ms": total_elapsed,
            "data": {
                "response": response_text,
                "model": model_used,
                "provider": provider,
                "context_used": context_used,
                "provenance": provenance
            },
            "error": None
        }
    
    except RouterClientError as e:
        total_elapsed = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "service": "api-gateway",
            "operation": "chat",
            "correlation_id": correlation_id,
            "duration_ms": total_elapsed,
            "data": None,
            "error": {
                "code": e.code,
                "message": e.message,
                "details": e.details
            }
        }
    
    except Exception as e:
        total_elapsed = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "service": "api-gateway",
            "operation": "chat",
            "correlation_id": correlation_id,
            "duration_ms": total_elapsed,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e),
                "details": {"error_type": type(e).__name__}
            }
        }
