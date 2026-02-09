"""
Vision and Screenshot API Endpoints

Implements FastAPI endpoints for vision analysis, screenshot capture, and UI detection.
Supports SSE streaming for real-time results.
"""

import asyncio
import logging
import base64
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse
import aiohttp

from vision import (
    ScreenCapture,
    ImageProcessor,
    VisionClient,
    VisionProvider,
    ImageFormat
)
from ocr import OCREngine, OCRProvider
from ui_detection import UIElementDetector, DetectionModel, AccessibilityAnalyzer
from streaming import StreamingResponse as StreamingResponseEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

# Shared instances
screen_capture = ScreenCapture()
image_processor = ImageProcessor()
ocr_engine = OCREngine(primary_provider=OCRProvider.TESSERACT)
ui_detector = UIElementDetector(model_type=DetectionModel.YOLOV8)
accessibility_analyzer = AccessibilityAnalyzer()

# Vision clients for different providers
vision_clients = {
    VisionProvider.OLLAMA: VisionClient(provider=VisionProvider.OLLAMA),
    VisionProvider.OPENAI: VisionClient(provider=VisionProvider.OPENAI),
    VisionProvider.CLAUDE: VisionClient(provider=VisionProvider.CLAUDE),
}


@router.post("/screenshot/capture")
async def capture_screenshot(
    region: Optional[List[int]] = Query(None),
    format: str = Query("png"),
    quality: int = Query(85)
):
    """
    Capture screenshot from desktop.

    Query Parameters:
    - region: Optional [left, top, width, height] for partial capture
    - format: Output format (png, jpeg, webp)
    - quality: Compression quality (1-100)

    Returns:
    - Base64 encoded image data and metadata
    """
    try:
        # Capture screenshot
        region_tuple = tuple(region) if region and len(region) == 4 else None
        image_bytes = await screen_capture.capture_screenshot(region_tuple)

        # Process if needed
        if format.lower() != "png":
            image_bytes = await image_processor.compress_image(
                image_bytes,
                quality=quality,
                format=ImageFormat(format.lower())
            )

        # Get metadata
        metadata = await image_processor.get_image_metadata(image_bytes)

        # Encode to base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        return {
            "success": True,
            "data": image_b64,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/analyze")
async def analyze_image(
    image_data: str = Body(..., description="Base64 encoded image"),
    prompt: str = Body(...),
    provider: str = Query("ollama"),
    model: Optional[str] = Query(None),
    max_tokens: int = Query(1024),
    temperature: float = Query(0.7),
    stream: bool = Query(False)
):
    """
    Analyze image with vision model.

    Body:
    - image_data: Base64 encoded image
    - prompt: Analysis prompt

    Query Parameters:
    - provider: Vision provider (ollama, openai, claude)
    - model: Model name (optional, uses default)
    - max_tokens: Max response tokens
    - temperature: Response temperature (0.0-1.0)
    - stream: Enable SSE streaming

    Returns:
    - Analysis result or SSE stream
    """
    try:
        # Decode image
        image_bytes = base64.b64decode(image_data)

        # Get vision client
        vision_provider = VisionProvider(provider.lower())
        if vision_provider not in vision_clients:
            raise ValueError(f"Unsupported provider: {provider}")

        client = vision_clients[vision_provider]

        if stream:
            # Stream response using SSE
            async def stream_analysis():
                stream_response = StreamingResponseEngine()
                
                try:
                    yield stream_response._format_sse({
                        "type": "analysis_start",
                        "provider": provider,
                        "model": model or "default",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    })

                    result = await client.analyze_image(
                        image_bytes,
                        prompt,
                        model,
                        max_tokens,
                        temperature
                    )

                    # Stream result in chunks
                    chunk_size = 50
                    for i in range(0, len(result), chunk_size):
                        chunk = result[i:i + chunk_size]
                        yield stream_response._format_sse({
                            "type": "text_chunk",
                            "content": chunk
                        })
                        await asyncio.sleep(0.01)

                    yield stream_response._format_sse({
                        "type": "analysis_complete",
                        "total_length": len(result)
                    })

                except Exception as e:
                    logger.error(f"Streaming analysis failed: {e}")
                    yield stream_response._format_sse({
                        "type": "error",
                        "error": str(e)
                    })

            return StreamingResponse(
                stream_analysis(),
                media_type="text/event-stream"
            )
        else:
            # Non-streaming response
            result = await client.analyze_image(
                image_bytes,
                prompt,
                model,
                max_tokens,
                temperature
            )

            return {
                "success": True,
                "result": result,
                "provider": provider,
                "model": model or "default",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ocr/extract")
async def extract_text_ocr(
    image_data: str = Body(...),
    provider: str = Query("tesseract"),
    language: Optional[str] = Query(None),
    return_boxes: bool = Query(False)
):
    """
    Extract text from image using OCR.

    Body:
    - image_data: Base64 encoded image

    Query Parameters:
    - provider: OCR provider (tesseract, paddle, ollama)
    - language: Language code (optional)
    - return_boxes: Include bounding boxes

    Returns:
    - Extracted text and optional bounding boxes
    """
    try:
        image_bytes = base64.b64decode(image_data)
        ocr_provider = OCRProvider(provider.lower())

        if return_boxes:
            boxes = await ocr_engine.extract_boxes(
                image_bytes,
                language,
                ocr_provider
            )

            return {
                "success": True,
                "text": "\n".join(b.text for b in boxes),
                "boxes": [
                    {
                        "text": b.text,
                        "confidence": b.confidence,
                        "bbox": b.bbox,
                        "language": b.language
                    }
                    for b in boxes
                ],
                "provider": provider,
                "total_boxes": len(boxes)
            }
        else:
            text = await ocr_engine.extract_text(
                image_bytes,
                language,
                ocr_provider
            )

            return {
                "success": True,
                "text": text,
                "provider": provider,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ui/detect")
async def detect_ui_elements(
    image_data: str = Body(...),
    confidence_threshold: float = Query(0.5),
    extract_text: bool = Query(True),
    stream: bool = Query(False)
):
    """
    Detect UI elements in screenshot.

    Body:
    - image_data: Base64 encoded image

    Query Parameters:
    - confidence_threshold: Minimum detection confidence
    - extract_text: Extract text from elements
    - stream: Enable SSE streaming

    Returns:
    - Detected UI elements or SSE stream
    """
    try:
        image_bytes = base64.b64decode(image_data)

        # Extract OCR data if needed
        ocr_data = None
        if extract_text:
            try:
                boxes = await ocr_engine.extract_boxes(image_bytes)
                ocr_data = {
                    "boxes": [
                        {
                            "text": b.text,
                            "confidence": b.confidence,
                            "bbox": b.bbox
                        }
                        for b in boxes
                    ]
                }
            except Exception as e:
                logger.warning(f"OCR extraction skipped: {e}")

        if stream:
            # Stream detection results
            async def stream_detection():
                stream_response = StreamingResponseEngine()

                try:
                    yield stream_response._format_sse({
                        "type": "detection_start",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    })

                    analysis = await ui_detector.detect(
                        image_bytes,
                        confidence_threshold,
                        extract_text,
                        ocr_data
                    )

                    yield stream_response._format_sse({
                        "type": "detection_progress",
                        "total_elements": analysis.total_elements
                    })

                    # Stream each element
                    for element in analysis.elements:
                        yield stream_response._format_sse({
                            "type": "element_detected",
                            "element": element.to_dict()
                        })
                        await asyncio.sleep(0.01)

                    yield stream_response._format_sse({
                        "type": "detection_complete",
                        "detection_time_ms": analysis.detection_time_ms
                    })

                except Exception as e:
                    logger.error(f"Streaming detection failed: {e}")
                    yield stream_response._format_sse({
                        "type": "error",
                        "error": str(e)
                    })

            return StreamingResponse(
                stream_detection(),
                media_type="text/event-stream"
            )
        else:
            # Non-streaming detection
            analysis = await ui_detector.detect(
                image_bytes,
                confidence_threshold,
                extract_text,
                ocr_data
            )

            return {
                "success": True,
                "elements": [e.to_dict() for e in analysis.elements],
                "total_elements": analysis.total_elements,
                "image_dimensions": {
                    "width": analysis.image_width,
                    "height": analysis.image_height
                },
                "detection_time_ms": analysis.detection_time_ms,
                "model": analysis.model_used
            }

    except Exception as e:
        logger.error(f"UI detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ui/localize")
async def localize_element(
    image_data: str = Body(...),
    element_label: str = Body(...),
    fuzzy_match: bool = Query(True)
):
    """
    Find specific UI element by label.

    Body:
    - image_data: Base64 encoded image
    - element_label: Label or text to find

    Query Parameters:
    - fuzzy_match: Allow approximate matching

    Returns:
    - Located element or 404 if not found
    """
    try:
        image_bytes = base64.b64decode(image_data)

        element = await ui_detector.localize_element(
            image_bytes,
            element_label,
            fuzzy_match
        )

        if not element:
            raise HTTPException(
                status_code=404,
                detail=f"Element '{element_label}' not found"
            )

        return {
            "success": True,
            "element": element.to_dict(),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Element localization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accessibility/analyze")
async def analyze_accessibility(
    image_data: str = Body(...)
):
    """
    Analyze UI for accessibility issues.

    Body:
    - image_data: Base64 encoded image

    Returns:
    - Accessibility report with issues and suggestions
    """
    try:
        image_bytes = base64.b64decode(image_data)

        # Detect UI elements
        analysis = await ui_detector.detect(image_bytes, extract_text=True)

        # Analyze accessibility
        report = await accessibility_analyzer.analyze(analysis)

        return {
            "success": True,
            "report": report,
            "total_elements_analyzed": analysis.total_elements,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Accessibility analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/process")
async def process_image(
    image_data: str = Body(...),
    operation: str = Body(...),
    parameters: Optional[Dict[str, Any]] = Body(None)
):
    """
    Apply image processing operations.

    Body:
    - image_data: Base64 encoded image
    - operation: Operation type (resize, compress, crop, convert)
    - parameters: Operation-specific parameters

    Returns:
    - Processed image data
    """
    try:
        image_bytes = base64.b64decode(image_data)
        params = parameters or {}

        if operation == "resize":
            processed = await image_processor.resize_image(
                image_bytes,
                max_width=params.get("max_width", 1920),
                max_height=params.get("max_height", 1080),
                maintain_aspect=params.get("maintain_aspect", True)
            )
        elif operation == "compress":
            processed = await image_processor.compress_image(
                image_bytes,
                quality=params.get("quality", 85),
                format=ImageFormat(params.get("format", "jpeg"))
            )
        elif operation == "crop":
            region = params.get("region", (0, 0, 100, 100))
            processed = await image_processor.crop_image(image_bytes, tuple(region))
        elif operation == "convert":
            target_format = ImageFormat(params.get("format", "png"))
            processed = await image_processor.convert_format(image_bytes, target_format)
        else:
            raise ValueError(f"Unknown operation: {operation}")

        processed_b64 = base64.b64encode(processed).decode('utf-8')
        metadata = await image_processor.get_image_metadata(processed)

        return {
            "success": True,
            "data": processed_b64,
            "operation": operation,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        logger.error(f"Image processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "vision-api",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
