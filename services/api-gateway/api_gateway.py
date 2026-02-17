"""
API Gateway Service

Main FastAPI application for Sonia's API Gateway.
Integrates vision, streaming, and voice services.
Implements request routing, middleware, and service orchestration.
"""

import logging
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

# Import API routers
from api.vision_endpoints import router as vision_router

logger = logging.getLogger(__name__)


class APIGatewayConfig:
    """API Gateway configuration."""

    def __init__(self):
        """Initialize configuration from environment."""
        self.port = int(os.getenv("API_GATEWAY_PORT", 7010))
        self.host = os.getenv("API_GATEWAY_HOST", "0.0.0.0")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # Service URLs
        self.voice_service_url = os.getenv("VOICE_SERVICE_URL", "http://localhost:7030")
        self.memory_service_url = os.getenv("MEMORY_SERVICE_URL", "http://localhost:7000")
        self.tool_service_url = os.getenv("TOOL_SERVICE_URL", "http://localhost:7080")
        
        # Vision settings
        self.default_vision_provider = os.getenv("VISION_PROVIDER", "ollama")
        self.default_ocr_provider = os.getenv("OCR_PROVIDER", "tesseract")
        self.default_detection_model = os.getenv("DETECTION_MODEL", "yolov8")
        
        # CORS settings
        self.cors_origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:3001"
        ).split(",")


config = APIGatewayConfig()


class RequestIDMiddleware:
    """Middleware to add request IDs for tracing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next):
        import uuid
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


class ErrorHandlingMiddleware:
    """Middleware for centralized error handling."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unhandled error in {request.method} {request.url.path}: {e}",
                exc_info=True
            )
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Internal server error",
                    "request_id": getattr(request.state, "request_id", None)
                }
            )


class ServiceHealthChecker:
    """Checks health of dependent services."""

    def __init__(self):
        """Initialize health checker."""
        self.logger = logging.getLogger(f"{__name__}.ServiceHealthChecker")

    async def check_voice_service(self) -> bool:
        """Check voice service health."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{config.voice_service_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            self.logger.warning(f"Voice service health check failed: {e}")
            return False

    async def check_memory_service(self) -> bool:
        """Check memory service health."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{config.memory_service_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            self.logger.warning(f"Memory service health check failed: {e}")
            return False

    async def check_all_services(self) -> dict:
        """Check all services."""
        return {
            "voice_service": await self.check_voice_service(),
            "memory_service": await self.check_memory_service(),
        }


health_checker = ServiceHealthChecker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown.
    
    Handles service initialization and cleanup.
    """
    # Startup
    logger.info("API Gateway starting up...")
    
    # Initialize vision components
    logger.info("Initializing vision components...")
    
    # Check dependent services
    service_status = await health_checker.check_all_services()
    logger.info(f"Service health check: {service_status}")
    
    yield
    
    # Shutdown
    logger.info("API Gateway shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Sonia API Gateway",
    description="Central API Gateway for Sonia platform",
    version="1.0.0",
    lifespan=lifespan
)


# Add middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(RequestIDMiddleware)
app.middleware("http")(ErrorHandlingMiddleware)


# Include routers
app.include_router(vision_router)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Sonia API Gateway",
        "version": "1.0.0",
        "status": "operational"
    }


# Health check endpoint
@app.get("/health")
async def health():
    """
    Health check endpoint.
    
    Returns service health status and dependent service status.
    """
    service_status = await health_checker.check_all_services()
    
    overall_healthy = all(service_status.values())
    
    return {
        "status": "healthy" if overall_healthy else "degraded",
        "api_gateway": "healthy",
        "services": service_status,
        "timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z"
    }


# Service status endpoint
@app.get("/status")
async def status():
    """
    Get detailed service status.
    
    Returns configuration and service status.
    """
    service_status = await health_checker.check_all_services()
    
    return {
        "service": "Sonia API Gateway",
        "port": config.port,
        "cors_enabled": True,
        "vision_provider": config.default_vision_provider,
        "ocr_provider": config.default_ocr_provider,
        "detection_model": config.default_detection_model,
        "services": service_status,
        "timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z"
    }


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "request_id": getattr(request.state, "request_id", None)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "request_id": getattr(request.state, "request_id", None)
        }
    )


def main():
    """Main entry point."""
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")
    logger.info(f"Vision Provider: {config.default_vision_provider}")
    logger.info(f"OCR Provider: {config.default_ocr_provider}")
    logger.info(f"Detection Model: {config.default_detection_model}")
    
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower()
    )


if __name__ == "__main__":
    main()
