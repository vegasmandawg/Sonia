"""
Tool Service

Main FastAPI service for tool management and execution.
Integrates registry, executor, and API endpoints.
"""

import logging
import os
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.responses import JSONResponse
import uvicorn

from tool_registry import (
    ToolRegistry,
    RiskTier,
    ToolCategory,
    get_registry
)
from executor import (
    ToolExecutor,
    ExecutionRequest,
    ExecutionStatus
)
from standard_tools import register_standard_tools

logger = logging.getLogger(__name__)


class ToolServiceConfig:
    """Tool Service configuration."""

    def __init__(self):
        """Initialize configuration from environment."""
        self.port = int(os.getenv("TOOL_SERVICE_PORT", 7040))
        self.host = os.getenv("TOOL_SERVICE_HOST", "0.0.0.0")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.catalog_path = os.getenv("TOOL_CATALOG_PATH", None)


config = ToolServiceConfig()
registry = get_registry()
executor = ToolExecutor(registry)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown.
    """
    # Startup
    logger.info("Tool Service starting up...")
    
    # Register standard tools
    register_standard_tools(registry)
    
    # Load custom catalog if provided
    if config.catalog_path:
        logger.info(f"Loading tool catalog from {config.catalog_path}")
        registry.import_catalog(config.catalog_path)
    
    logger.info(f"Tool Service initialized with {len(registry.tools)} tools")
    
    yield
    
    # Shutdown
    logger.info("Tool Service shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Sonia Tool Service",
    description="Tool execution and management service",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# Tool Discovery Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Sonia Tool Service",
        "version": "1.0.0",
        "status": "operational"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    health_status = registry.health_check()
    return health_status


@app.get("/api/v1/tools")
async def list_tools(
    category: Optional[str] = Query(None),
    risk_tier: Optional[str] = Query(None),
    tag: Optional[str] = Query(None)
):
    """
    List available tools with optional filtering.

    Query Parameters:
    - category: Filter by category (filesystem, network, computation, etc.)
    - risk_tier: Filter by risk tier (tier_0, tier_1, tier_2, tier_3)
    - tag: Filter by tag

    Returns:
    - Array of tool definitions
    """
    try:
        # Parse filters
        category_enum = ToolCategory(category) if category else None
        risk_tier_enum = RiskTier(risk_tier) if risk_tier else None

        # List tools
        tools = registry.list_tools(
            category=category_enum,
            risk_tier=risk_tier_enum,
            tag=tag
        )

        return {
            "success": True,
            "total_tools": len(tools),
            "tools": [t.to_dict() for t in tools]
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"List tools failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/tools/{tool_name}")
async def get_tool(tool_name: str):
    """
    Get specific tool definition.

    Path Parameters:
    - tool_name: Tool name or alias

    Returns:
    - Tool definition or 404
    """
    tool = registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )

    return {
        "success": True,
        "tool": tool.to_dict()
    }


@app.get("/api/v1/tools/{tool_name}/stats")
async def get_tool_stats(tool_name: str):
    """
    Get tool execution statistics.

    Path Parameters:
    - tool_name: Tool name

    Returns:
    - Tool statistics or 404
    """
    stats = registry.get_stats(tool_name)
    if not stats:
        raise HTTPException(
            status_code=404,
            detail=f"No statistics for tool: {tool_name}"
        )

    return {
        "success": True,
        "stats": stats.to_dict()
    }


# ============================================================================
# Tool Execution Endpoints
# ============================================================================

@app.post("/api/v1/tools/{tool_name}/execute")
async def execute_tool(
    tool_name: str,
    parameters: Dict[str, Any] = Body(...),
    user_id: Optional[str] = Query(None),
    approved: bool = Query(False)
):
    """
    Execute a tool.

    Path Parameters:
    - tool_name: Tool name

    Body:
    - parameters: Dictionary of tool parameters

    Query Parameters:
    - user_id: User identifier (optional)
    - approved: Whether execution is pre-approved

    Returns:
    - Execution result with status and output
    """
    try:
        # Create execution request
        request = ExecutionRequest(
            tool_name=tool_name,
            parameters=parameters,
            user_id=user_id
        )

        # Execute tool
        result = await executor.execute(request, user_approved=approved)

        # Return result
        status_code = 200 if result.status == ExecutionStatus.COMPLETED else 400
        if result.status == ExecutionStatus.REQUIRES_APPROVAL:
            status_code = 202  # Accepted but requires approval

        return JSONResponse(
            status_code=status_code,
            content={
                "success": result.status == ExecutionStatus.COMPLETED,
                "result": result.to_dict()
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/tools/batch-execute")
async def batch_execute_tools(
    requests: List[Dict[str, Any]] = Body(...),
    user_id: Optional[str] = Query(None),
    approved: bool = Query(False),
    parallel: bool = Query(False)
):
    """
    Execute multiple tools.

    Body:
    - requests: Array of execution requests
      Each request: {
        "tool_name": string,
        "parameters": object
      }

    Query Parameters:
    - user_id: User identifier
    - approved: Whether all executions are pre-approved
    - parallel: Execute in parallel (default: sequential)

    Returns:
    - Array of execution results
    """
    try:
        # Create execution requests
        exec_requests = [
            ExecutionRequest(
                tool_name=req["tool_name"],
                parameters=req.get("parameters", {}),
                user_id=user_id
            )
            for req in requests
        ]

        # Execute batch
        results = await executor.batch_execute(
            exec_requests,
            user_approved=approved,
            parallel=parallel
        )

        return {
            "success": True,
            "total_requests": len(results),
            "completed": sum(1 for r in results if r.status == ExecutionStatus.COMPLETED),
            "failed": sum(1 for r in results if r.status == ExecutionStatus.FAILED),
            "results": [r.to_dict() for r in results]
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Batch execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/executions")
async def get_execution_history(
    tool_name: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """
    Get execution history.

    Query Parameters:
    - tool_name: Filter by tool name
    - limit: Max results (default: 100)

    Returns:
    - Array of execution results
    """
    history = executor.get_execution_history(tool_name, limit)

    return {
        "success": True,
        "total_results": len(history),
        "executions": [r.to_dict() for r in history]
    }


@app.get("/api/v1/executions/{request_id}")
async def get_execution_result(request_id: str):
    """
    Get specific execution result.

    Path Parameters:
    - request_id: Execution request ID

    Returns:
    - Execution result or 404
    """
    result = executor.execution_history.get(request_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Execution not found: {request_id}"
        )

    return {
        "success": True,
        "result": result.to_dict()
    }


# ============================================================================
# Catalog Management Endpoints
# ============================================================================

@app.get("/api/v1/catalog/export")
async def export_catalog():
    """
    Export complete tool catalog.

    Returns:
    - JSON catalog with all tool definitions and statistics
    """
    catalog = registry.export_catalog()

    return {
        "success": True,
        "catalog": catalog
    }


@app.post("/api/v1/catalog/import")
async def import_catalog(catalog_path: str = Body(...)):
    """
    Import tools from catalog file.

    Body:
    - catalog_path: Path to catalog JSON file

    Returns:
    - Import result with count
    """
    success = registry.import_catalog(catalog_path)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to import catalog from {catalog_path}"
        )

    return {
        "success": True,
        "total_tools": len(registry.tools),
        "message": f"Imported tools from {catalog_path}"
    }


# ============================================================================
# Statistics and Monitoring Endpoints
# ============================================================================

@app.get("/api/v1/stats")
async def get_statistics():
    """
    Get aggregate statistics.

    Returns:
    - Service statistics and health status
    """
    health = registry.health_check()
    all_stats = registry.get_all_stats()

    return {
        "success": True,
        "health": health,
        "tools": {
            name: stats.to_dict()
            for name, stats in all_stats.items()
        }
    }


@app.delete("/api/v1/executions/history")
async def clear_execution_history():
    """
    Clear execution history.

    Returns:
    - Count of cleared entries
    """
    count = executor.clear_history()

    return {
        "success": True,
        "cleared_entries": count
    }


def main():
    """Main entry point."""
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"Starting Tool Service on {config.host}:{config.port}")

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower()
    )


if __name__ == "__main__":
    main()
