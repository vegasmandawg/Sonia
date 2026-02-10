"""
Sonia Model Router - Main Entry Point

Provider abstraction and model routing with support for:
- Ollama (local, default)
- Anthropic Claude (optional, via API key)
- OpenRouter (optional, via API key)
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel

# Canonical version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION

from providers import (
    get_router, TaskType, ProviderRouter, ModelInfo
)

# Profile infrastructure (lazy-init at startup)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('model-router')

# Initialize provider router
router = get_router()

# Profile infrastructure (initialised in startup handler)
_routing_engine = None
_health_registry = None
_budget_guard = None
_audit_logger = None

# Create FastAPI app (lifespan defined below, assigned after)
app = FastAPI(
    title="Sonia Model Router",
    description="Model and provider routing for Sonia",
    version=SONIA_VERSION,
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
    policy: Optional[str] = "cloud_allowed"  # local_only, cloud_allowed, provider_pinned
    provider: Optional[str] = None  # For provider_pinned policy

class ProfileRouteRequest(BaseModel):
    task_type: str = ""
    hint: str = ""
    trace_id: str = ""
    turn_id: str = ""
    context_tokens: int = 0

# ─────────────────────────────────────────────────────────────────────────────
# Health & Status Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Health check endpoint with profile diagnostics."""
    available_providers = len([p for p in router.providers.values() if p.available])
    result = {
        "ok": True,
        "service": "model-router",
        "timestamp": datetime.utcnow().isoformat(),
        "available_providers": available_providers,
    }
    if _routing_engine is not None:
        result["profiles"] = {
            "loaded": _routing_engine.registry.names,
            "validation_errors": _routing_engine.registry.validation_errors,
        }
    if _health_registry is not None:
        result["backend_health"] = _health_registry.all_health()
        result["quarantined"] = _health_registry.quarantined_backends()
    if _audit_logger is not None:
        result["audit"] = _audit_logger.to_dict()
    return result

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "model-router",
        "status": "online",
        "version": SONIA_VERSION
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
        return route(request.task_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Selection error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/chat")
async def chat(request: ChatRequest):
    """Send chat request to routed provider with policy support."""
    try:
        # Validate task type
        try:
            task = TaskType[request.task_type.upper()]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown task type: {request.task_type}"
            )

        policy = request.policy or "cloud_allowed"
        extra_kwargs = {}
        if request.temperature is not None:
            extra_kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            extra_kwargs["max_tokens"] = request.max_tokens

        # Policy-based routing
        if policy == "provider_pinned" and request.provider:
            # Direct provider dispatch
            provider = router.providers.get(request.provider)
            if not provider:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown provider: {request.provider}"
                )
            if not provider.available:
                raise HTTPException(
                    status_code=503,
                    detail=f"Provider not available: {request.provider}"
                )
            model_info = provider.route(task)
            if not model_info:
                raise HTTPException(
                    status_code=503,
                    detail=f"No model for task {request.task_type} on {request.provider}"
                )
            result = provider.chat(model_info.name, request.messages, **extra_kwargs)

        elif policy == "local_only":
            # Only use local providers (ollama)
            provider = router.providers.get("ollama")
            if not provider or not provider.available:
                raise HTTPException(
                    status_code=503,
                    detail="No local provider available"
                )
            model_info = provider.route(task)
            if not model_info:
                raise HTTPException(
                    status_code=503,
                    detail=f"No local model for task: {request.task_type}"
                )
            result = provider.chat(model_info.name, request.messages, **extra_kwargs)

        else:
            # cloud_allowed (default): try local first, fall back to cloud
            result = router.chat(task, request.messages, **extra_kwargs)

        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result.get("error"))
        if result.get("status") == "not_implemented":
            raise HTTPException(status_code=501, detail=result.get("error"))

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
# Profile-Based Routing Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/route-profile")
async def route_profile(request: ProfileRouteRequest):
    """Route via deterministic profile selection."""
    if _routing_engine is None:
        raise HTTPException(status_code=503, detail="Profile engine not initialised")
    decision = _routing_engine.route_request(
        task_type=request.task_type,
        hint=request.hint,
        trace_id=request.trace_id,
        context_tokens=request.context_tokens,
    )
    if _audit_logger is not None:
        _audit_logger.log_decision(decision, turn_id=request.turn_id)
    return decision.to_dict()

@app.get("/profiles")
def get_profiles():
    """List all loaded routing profiles."""
    if _routing_engine is None:
        return {"profiles": {}, "service": "model-router"}
    return {
        "profiles": _routing_engine.registry.to_dict()["profiles"],
        "service": "model-router",
    }

@app.get("/route-audit")
def get_route_audit(n: int = 20):
    """Return recent route audit records."""
    if _audit_logger is None:
        return {"records": [], "service": "model-router"}
    return {
        "records": _audit_logger.read_recent(n),
        "total_written": _audit_logger.record_count,
        "service": "model-router",
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

@asynccontextmanager
async def _lifespan(a):
    """Startup and shutdown lifecycle for Model Router."""
    global _routing_engine, _health_registry, _budget_guard, _audit_logger

    logger.info("Model Router starting up...")

    available = [
        name for name, p in router.providers.items() if p.available
    ]
    logger.info(f"Available providers: {', '.join(available) if available else 'none'}")

    all_models = router.get_all_models()
    total = sum(len(models) for models in all_models.values())
    logger.info(f"Total available models: {total}")

    # ---- Initialise profile infrastructure --------------------------------
    try:
        _app_dir = str(Path(__file__).resolve().parent)
        if _app_dir not in sys.path:
            sys.path.insert(0, _app_dir)

        from app.profiles import ProfileRegistry
        from app.routing_engine import RoutingEngine
        from app.health_registry import HealthRegistry
        from app.budget_guard import BudgetGuard
        from app.route_audit import RouteAuditLogger

        # Load config
        cfg_path = Path(r"S:\config\sonia-config.json")
        mr_cfg = {}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                full_cfg = json.load(f)
            mr_cfg = full_cfg.get("model_router", {})

        profiles_cfg = mr_cfg.get("profiles", {})
        health_cfg = mr_cfg.get("health", {})

        # Health registry
        _health_registry = HealthRegistry(
            failure_window_s=health_cfg.get("failure_window_s", 60),
            failure_threshold=health_cfg.get("failure_threshold", 3),
            quarantine_s=health_cfg.get("quarantine_s", 30),
            recovery_probes=health_cfg.get("recovery_probes", 2),
        )

        # Budget guard with known backend capacities
        _budget_guard = BudgetGuard()
        for cap_entry in profiles_cfg.get("backend_capacities", []):
            _budget_guard.register_backend(
                backend=cap_entry.get("backend", ""),
                max_context=cap_entry.get("max_context", 8000),
                avg_latency_ms=cap_entry.get("avg_latency_ms", 1000),
            )

        # Profile registry with defaults
        _profile_registry = ProfileRegistry()

        # Routing engine
        _routing_engine = RoutingEngine(
            registry=_profile_registry,
            is_healthy=_health_registry.is_healthy,
            check_budget=_budget_guard.check,
        )

        # Audit logger
        audit_path = mr_cfg.get("audit_log_path",
                                r"S:\logs\services\model-router\routes.jsonl")
        _audit_logger = RouteAuditLogger(path=audit_path)

        logger.info("Profile infrastructure initialised: %d profiles, audit -> %s",
                     len(_profile_registry.names), audit_path)

    except Exception as e:
        logger.error("Failed to initialise profile infrastructure: %s", e, exc_info=True)
        # Service remains healthy -- legacy routing still works

    yield  # ── app is running ──

    logger.info("Model Router shutting down...")

app.router.lifespan_context = _lifespan

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
