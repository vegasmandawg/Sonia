"""
Orchestrator Service

Main FastAPI service for agent orchestration and multimodal coordination.
Exposes agent functionality via REST API.
"""

import logging
import os
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Body, Query, WebSocket
from fastapi.responses import JSONResponse
import uvicorn

from agent import Agent, AgentConfig, AgentState

logger = logging.getLogger(__name__)


class OrchestratorConfig:
    """Orchestrator service configuration."""

    def __init__(self):
        """Initialize configuration from environment."""
        self.port = int(os.getenv("ORCHESTRATOR_PORT", 8000))
        self.host = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # Agent config
        self.agent_name = os.getenv("AGENT_NAME", "Sonia")
        self.enable_memory = os.getenv("ENABLE_MEMORY", "true").lower() == "true"
        self.enable_vision = os.getenv("ENABLE_VISION", "true").lower() == "true"
        self.enable_tools = os.getenv("ENABLE_TOOLS", "true").lower() == "true"


config = OrchestratorConfig()


def create_agent() -> Agent:
    """Create and configure agent."""
    agent_config = AgentConfig(
        name=config.agent_name,
        enable_memory=config.enable_memory,
        enable_vision=config.enable_vision,
        enable_tools=config.enable_tools
    )
    return Agent(agent_config)


agent = create_agent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info(f"Orchestrator Service starting up (Agent: {config.agent_name})")
    logger.info(f"Memory: {config.enable_memory}, Vision: {config.enable_vision}, Tools: {config.enable_tools}")
    
    yield
    
    # Shutdown
    logger.info("Orchestrator Service shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Sonia Orchestrator",
    description="Multimodal agent orchestration service",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# Agent Interaction Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Sonia Orchestrator",
        "version": "1.0.0",
        "agent": config.agent_name,
        "status": "operational"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent": config.agent_name,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.post("/api/v1/agent/process")
async def process_user_input(
    message: str = Body(...),
    conversation_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    auto_execute: bool = Query(True)
):
    """
    Process user input and generate agent response.

    Body:
    - message: User message

    Query Parameters:
    - conversation_id: Unique conversation identifier (auto-generated if not provided)
    - user_id: User identifier (optional)
    - auto_execute: Automatically execute approved actions (default: true)

    Returns:
    - Agent execution context with response and action results
    """
    try:
        # Process input
        context = await agent.process_input(
            user_message=message,
            conversation_id=conversation_id,
            user_id=user_id,
            auto_execute=auto_execute
        )

        return {
            "success": True,
            "context": context.to_dict(),
            "response": context.response_text,
            "actions_executed": len(context.actions_taken),
            "confidence": context.confidence_score,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/agent/status")
async def get_agent_status():
    """
    Get current agent status.

    Returns:
    - Agent configuration and status
    """
    return {
        "agent_id": agent.config.agent_id,
        "name": agent.config.name,
        "description": agent.config.description,
        "features": {
            "memory": agent.config.enable_memory,
            "vision": agent.config.enable_vision,
            "tools": agent.config.enable_tools
        },
        "active_conversations": len(agent.execution_contexts),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ============================================================================
# Conversation Management Endpoints
# ============================================================================

@app.get("/api/v1/conversations")
async def list_conversations(limit: int = Query(10)):
    """
    List recent conversations.

    Query Parameters:
    - limit: Max results (default: 10)

    Returns:
    - Array of conversation summaries
    """
    contexts = agent.list_contexts(limit)

    return {
        "success": True,
        "total": len(contexts),
        "conversations": [c.to_dict() for c in contexts]
    }


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """
    Get specific conversation.

    Path Parameters:
    - conversation_id: Conversation identifier

    Returns:
    - Full conversation context or 404
    """
    context = agent.get_context(conversation_id)
    if not context:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation not found: {conversation_id}"
        )

    return {
        "success": True,
        "context": context.to_dict(),
        "actions": [
            {
                "action_id": a.action_id,
                "type": a.action_type.value,
                "target": a.target,
                "reasoning": a.reasoning,
                "timestamp": a.timestamp
            }
            for a in context.actions_taken
        ],
        "results": context.action_results
    }


@app.post("/api/v1/conversations/{conversation_id}/continue")
async def continue_conversation(
    conversation_id: str,
    message: str = Body(...),
    auto_execute: bool = Query(True)
):
    """
    Continue existing conversation.

    Path Parameters:
    - conversation_id: Conversation to continue

    Body:
    - message: User message

    Query Parameters:
    - auto_execute: Automatically execute approved actions

    Returns:
    - Updated conversation context
    """
    existing_context = agent.get_context(conversation_id)
    if not existing_context:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation not found: {conversation_id}"
        )

    try:
        # Process in existing conversation
        context = await agent.process_input(
            user_message=message,
            conversation_id=conversation_id,
            user_id=existing_context.user_id,
            auto_execute=auto_execute
        )

        return {
            "success": True,
            "context": context.to_dict(),
            "response": context.response_text,
            "total_actions": len(context.actions_taken),
            "confidence": context.confidence_score
        }

    except Exception as e:
        logger.error(f"Continuation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Vision Integration Endpoints
# ============================================================================

@app.post("/api/v1/agent/analyze-screenshot")
async def analyze_screenshot(
    conversation_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """
    Capture and analyze screenshot.

    Query Parameters:
    - conversation_id: Associate with conversation
    - user_id: User identifier

    Returns:
    - Screenshot analysis result
    """
    try:
        # Capture screenshot
        screenshot = await agent.vision_handler.capture_screenshot()
        if not screenshot:
            raise HTTPException(status_code=500, detail="Screenshot capture failed")

        # Detect UI elements
        elements = await agent.vision_handler.detect_ui_elements(screenshot)

        # Analyze with vision model
        analysis = await agent.vision_handler.analyze_screenshot(
            screenshot,
            "Analyze this screenshot and describe what you see"
        )

        return {
            "success": True,
            "screenshot_captured": True,
            "ui_elements_detected": len(elements) if elements else 0,
            "analysis": analysis,
            "elements": elements,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Screenshot analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Tool Execution Endpoints
# ============================================================================

@app.post("/api/v1/agent/execute-tool")
async def execute_tool(
    tool_name: str = Query(...),
    parameters: Dict[str, Any] = Body(...),
    conversation_id: Optional[str] = Query(None),
    auto_execute: bool = Query(True)
):
    """
    Execute a tool.

    Query Parameters:
    - tool_name: Name of tool to execute
    - conversation_id: Associate with conversation
    - auto_execute: Auto-approve execution

    Body:
    - parameters: Tool parameters

    Returns:
    - Tool execution result
    """
    try:
        result = await agent.tool_executor.execute_tool(
            tool_name,
            parameters,
            approved=auto_execute
        )

        # Store in conversation if provided
        if conversation_id:
            context = agent.get_context(conversation_id)
            if context:
                context.action_results[tool_name] = result

        return {
            "success": result.get("success", False),
            "tool": tool_name,
            "result": result,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Memory Integration Endpoints
# ============================================================================

@app.post("/api/v1/agent/store-memory")
async def store_memory(
    content: str = Body(...),
    entity_type: str = Query("interaction"),
    conversation_id: Optional[str] = Query(None),
    metadata: Optional[Dict[str, Any]] = Body(None)
):
    """
    Store information in agent memory.

    Body:
    - content: Information to store

    Query Parameters:
    - entity_type: Type of entity (default: interaction)
    - conversation_id: Associate with conversation

    Returns:
    - Storage result
    """
    try:
        success = await agent.memory_manager.store_experience(
            content,
            entity_type=entity_type,
            metadata=metadata
        )

        return {
            "success": success,
            "stored": success,
            "content_length": len(content),
            "entity_type": entity_type,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Memory storage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/agent/retrieve-memory")
async def retrieve_memory(
    query: str = Body(...),
    limit: int = Query(5),
    conversation_id: Optional[str] = Query(None)
):
    """
    Retrieve information from agent memory.

    Body:
    - query: Search query

    Query Parameters:
    - limit: Max results
    - conversation_id: Associate with conversation

    Returns:
    - Retrieved memories
    """
    try:
        memories = await agent.memory_manager.retrieve_context(query, limit)

        return {
            "success": True,
            "query": query,
            "memories_found": len(memories),
            "memories": memories,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Memory retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Main entry point."""
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"Starting Orchestrator Service on {config.host}:{config.port}")

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower()
    )


if __name__ == "__main__":
    main()
