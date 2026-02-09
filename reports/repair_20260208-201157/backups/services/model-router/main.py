"""
Sonia Model Router - Main Entry Point

Provider abstraction and model routing with support for:
- Ollama (local, default)
- Anthropic Claude (optional, via API key)
- OpenRouter (optional, via API key)
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import sys
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel

from providers import (
    get_router, TaskType, ProviderRouter, ModelInfo
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('model-router')

# Initialize provider router
router = get_router()

# Create FastAPI app
app = FastAPI(
    title="Sonia Model Router",
    description="Model and provider routing for Sonia",
    version="1.0.0"
)

# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────

class SelectRequest(BaseModel):
    task_type: str = "text"  # text, vision, embeddings, reranker

class ChatRequest(BaseModel):
    task_type: str = "text"
    messages: List[Dict]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048

# ─────────────────────────────────────────────────────────────────────────────
# Health & Status Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    available_providers = len([p for p in router.providers.values() if p.available])
    return {
        "ok": True,
        "service": "model-router",
        "timestamp": datetime.utcnow().isoformat(),
        "available_providers": available_providers
    }

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "model-router",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/status")
def status():
    """Detailed status endpoint."""
    available_providers = {
        name: p.available for name, p in router.providers.items()
    }
    
    all_models = router.get_all_models()
    total_models = sum(len(models) for models in all_models.values())
    
    return {
        "service": "model-router",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "providers": {
            "available": available_providers,
            "count": len([p for p in router.providers.values() if p.available])
        },
        "models": {
            "total": total_models,
            "by_provider": {name: len(models) for name, models in all_models.items()}
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# Model Routing Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/route")
def route(task_type: str = "text"):
    """Route request to appropriate model."""
    try:
        # Validate task type
        try:
            task = TaskType[task_type.upper()]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown task type: {task_type}. Valid: text, vision, embeddings, reranker"
            )
        
        # Get best model for task
        model_info = router.route(task)
        
        if not model_info:
            raise HTTPException(
                status_code=503,
                detail=f"No available provider for task: {task_type}"
            )
        
        return {
            "task_type": task_type,
            "model": model_info.name,
            "provider": model_info.provider,
            "capabilities": model_info.capabilities,
            "config": model_info.config
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Routing error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/select")
async def select(request: SelectRequest):
    """Select model based on task requirements."""
    try:
        return await route(request.task_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Selection error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/chat")
async def chat(request: ChatRequest):
    """Send chat request to routed provider."""
    try:
        # Validate task type
        try:
            task = TaskType[request.task_type.upper()]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown task type: {request.task_type}"
            )
        
        # Route and execute
        result = router.chat(task, request.messages)
        
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result.get("error"))
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Provider Information Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/providers")
def list_providers():
    """List all configured providers."""
    providers_info = {}
    
    for name, provider in router.providers.items():
        providers_info[name] = {
            "available": provider.available,
            "endpoint": provider.endpoint,
            "models": len(provider.get_models()) if provider.available else 0
        }
    
    return {
        "providers": providers_info,
        "active_providers": [
            name for name, p in router.providers.items() if p.available
        ],
        "service": "model-router"
    }

@app.get("/models")
def list_models():
    """List all available models across all providers."""
    all_models = router.get_all_models()
    
    formatted = {}
    for provider_name, models in all_models.items():
        formatted[provider_name] = [
            {
                "name": m.name,
                "capabilities": m.capabilities,
                "config": m.config
            }
            for m in models
        ]
    
    return {
        "models": formatted,
        "total": sum(len(models) for models in formatted.values()),
        "service": "model-router"
    }

@app.get("/models/{provider_name}")
def list_provider_models(provider_name: str):
    """List models for specific provider."""
    if provider_name not in router.providers:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider: {provider_name}"
        )
    
    provider = router.providers[provider_name]
    
    if not provider.available:
        return {
            "provider": provider_name,
            "available": False,
            "models": [],
            "service": "model-router"
        }
    
    models = provider.get_models()
    
    return {
        "provider": provider_name,
        "available": True,
        "models": [
            {
                "name": m.name,
                "capabilities": m.capabilities,
                "config": m.config
            }
            for m in models
        ],
        "count": len(models),
        "service": "model-router"
    }

# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc),
            "service": "model-router"
        }
    )

# ─────────────────────────────────────────────────────────────────────────────
# Startup & Shutdown
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("Model Router starting up...")
    
    available = [
        name for name, p in router.providers.items() if p.available
    ]
    logger.info(f"Available providers: {', '.join(available) if available else 'none'}")
    
    all_models = router.get_all_models()
    total = sum(len(models) for models in all_models.values())
    logger.info(f"Total available models: {total}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Model Router shutting down...")

# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Model Router on http://127.0.0.1:7010")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7010,
        reload=False,
        log_level="info"
    )
